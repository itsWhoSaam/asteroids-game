/**
 * The WebAudio port of sound.py — procedural SFX, no binary assets. The
 * synthesis math (sound.py:131–215) is ported 1:1: the exact-phase chirp
 * integral, the shoot's exponential decay, the explosion's noise-over-thump
 * with per-tier tables, the powerup's triangle window, and the game-over
 * fade. The only divergence is the noise stream's generator: buffers use
 * the sim's mulberry32 (seeded, deterministic every run) rather than
 * CPython's Mersenne Twister — same contract, deterministic buffers.
 *
 * Failure safety is the desktop's contract: init and every play call are
 * guarded, a failure degrades to a silent no-op with one warning, and
 * muting suppresses playback only.
 */
import {
  SFX_EXPLOSION_TIERS,
  SFX_EXPLOSION_VOLUME,
  SFX_GAME_OVER_DURATION,
  SFX_GAME_OVER_SWEEP,
  SFX_GAME_OVER_VOLUME,
  SFX_NOISE_SEED,
  SFX_POWERUP_DURATION,
  SFX_POWERUP_SWEEP,
  SFX_POWERUP_VOLUME,
  SFX_SAMPLE_RATE,
  SFX_SHOOT_DURATION,
  SFX_SHOOT_SWEEP,
  SFX_SHOOT_VOLUME,
} from "../shared/constants";
import type { GameEvent } from "../shared/protocol";
import { mulberry32 } from "../shared/rng";

export type SfxName =
  | "shoot"
  | "explosion_small"
  | "explosion_medium"
  | "explosion_large"
  | "powerup"
  | "game_over";

export type ExplosionTier = keyof typeof SFX_EXPLOSION_TIERS;

/** Linear frequency sweep start→end Hz; exact chirp phase integral. */
export function chirp(t: number, startHz: number, endHz: number, duration: number): number {
  const mid = (startHz + endHz) / 2;
  const half = (endHz - startHz) / 2;
  return Math.sin(2 * Math.PI * (mid * t + (half * t * t) / duration));
}

/** The 'pew': descending chirp through a fast exponential decay. */
export function shootWave(t: number, progress: number): number {
  const [start, end] = SFX_SHOOT_SWEEP;
  return chirp(t, start, end, SFX_SHOOT_DURATION) * Math.exp(-6.0 * progress) * SFX_SHOOT_VOLUME;
}

/** Noise burst over a low thump — `noise` is the raw uniform draw in
 * [−1, 1); brightness scaling happens here, as in sound.py's wave. */
export function explosionWave(t: number, progress: number, tier: ExplosionTier, noise: number): number {
  const params = SFX_EXPLOSION_TIERS[tier];
  const decay = Math.exp(-4.0 * progress);
  const thump = chirp(t, params.thump_hz, params.thump_hz * 0.5, params.duration);
  return (noise * params.brightness + thump * (1.0 - progress)) * decay * SFX_EXPLOSION_VOLUME;
}

/** Rising chirp under a triangle attack/decay window — the pickup jingle. */
export function powerupWave(t: number, progress: number): number {
  const [start, end] = SFX_POWERUP_SWEEP;
  const window = Math.min(progress / 0.2, (1.0 - progress) / 0.3, 1.0);
  return chirp(t, start, end, SFX_POWERUP_DURATION) * Math.max(0.0, window) * SFX_POWERUP_VOLUME;
}

/** A long descending tone: the run winding down. */
export function gameOverWave(t: number, progress: number): number {
  const [start, end] = SFX_GAME_OVER_SWEEP;
  return chirp(t, start, end, SFX_GAME_OVER_DURATION) * (1.0 - progress) * SFX_GAME_OVER_VOLUME;
}

/** _render: sample wave(t, progress) over the duration, clamped to [−1, 1]. */
export function renderSamples(duration: number, wave: (t: number, progress: number) => number): number[] {
  const frames = Math.trunc(SFX_SAMPLE_RATE * duration);
  const samples = new Array<number>(frames);
  for (let i = 0; i < frames; i += 1) {
    const value = wave(i / SFX_SAMPLE_RATE, i / frames);
    samples[i] = Math.max(-1.0, Math.min(1.0, value));
  }
  return samples;
}

export function shootSamples(): number[] {
  return renderSamples(SFX_SHOOT_DURATION, shootWave);
}

export function explosionSamples(tier: ExplosionTier): number[] {
  // Seeded per buffer build: same sounds every run, same sounds in tests.
  const rng = mulberry32(SFX_NOISE_SEED);
  return renderSamples(SFX_EXPLOSION_TIERS[tier].duration, (t, progress) =>
    explosionWave(t, progress, tier, rng() * 2 - 1),
  );
}

export function powerupSamples(): number[] {
  return renderSamples(SFX_POWERUP_DURATION, powerupWave);
}

export function gameOverSamples(): number[] {
  return renderSamples(SFX_GAME_OVER_DURATION, gameOverWave);
}

/** The full synthesized table, filled once at init — the TS twin of
 * sound.init()'s _sounds dict. */
export function synthTable(): Array<[SfxName, number[]]> {
  return [
    ["shoot", shootSamples()],
    ["explosion_small", explosionSamples("small")],
    ["explosion_medium", explosionSamples("medium")],
    ["explosion_large", explosionSamples("large")],
    ["powerup", powerupSamples()],
    ["game_over", gameOverSamples()],
  ];
}

/** GameEvent explosion size → sound tier: 3 is the large rock. */
export function tierForSize(size: 1 | 2 | 3): ExplosionTier {
  switch (size) {
    case 3:
      return "large";
    case 2:
      return "medium";
    default:
      return "small";
  }
}

/** The playback half — the AudioContext glue. Pure sample math above;
 * everything here degrades to a silent no-op on failure, one warning. */
export class AudioSfx {
  private ctx: AudioContext | null = null;
  private readonly buffers = new Map<SfxName, AudioBuffer>();
  private muted = false;
  private degraded = false;

  setMuted(muted: boolean): void {
    this.muted = muted;
  }

  isMuted(): boolean {
    return this.muted;
  }

  /** Synthesize the buffer table once. Call from the first user gesture —
   * browsers hold AudioContexts suspended until then. */
  init(): void {
    if (this.degraded || this.buffers.size > 0) return;
    try {
      this.ctx ??= new AudioContext({ sampleRate: SFX_SAMPLE_RATE });
      for (const [name, samples] of synthTable()) {
        this.buffers.set(name, this.makeBuffer(samples));
      }
    } catch (error) {
      this.degrade(`mixer unavailable, running silent: ${String(error)}`);
    }
  }

  async resume(): Promise<void> {
    this.init();
    if (this.ctx && this.ctx.state === "suspended") {
      try {
        await this.ctx.resume();
      } catch (error) {
        this.degrade(`resume failed, running silent: ${String(error)}`);
      }
    }
  }

  play(name: SfxName): void {
    if (this.muted || this.degraded || !this.ctx) return;
    const buffer = this.buffers.get(name);
    if (!buffer) return;
    try {
      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(this.ctx.destination);
      source.start();
    } catch (error) {
      this.degrade(`playback failed, going silent: ${String(error)}`);
    }
  }

  playExplosion(size: 1 | 2 | 3): void {
    this.play(`explosion_${tierForSize(size)}`);
  }

  /** The GameEvent → SFX map, mirroring the desktop's sound calls:
   * shoot, explosions by tier, pickups, game over. playerHit, waveStarted,
   * purchase, mint, and burst had no sound in the Python build either —
   * they stay cosmetic-only here. */
  handleEvents(events: readonly GameEvent[]): void {
    for (const event of events) {
      switch (event.k) {
        case "shoot":
          this.play("shoot");
          break;
        case "explosion":
          this.playExplosion(event.size);
          break;
        case "pickup":
          this.play("powerup");
          break;
        case "gameOver":
          this.play("game_over");
          break;
        default:
          break;
      }
    }
  }

  private makeBuffer(samples: number[]): AudioBuffer {
    // _make_sound duplicated every sample across left and right; the
    // AudioBuffer equivalent is two identical channels of float data.
    const buffer = this.ctx!.createBuffer(2, samples.length, SFX_SAMPLE_RATE);
    for (let channel = 0; channel < 2; channel += 1) {
      buffer.copyToChannel(Float32Array.from(samples), channel);
    }
    return buffer;
  }

  private degrade(message: string): void {
    if (this.degraded) return;
    this.degraded = true;
    console.warn(`asteroids: [sound] warning: ${message}`);
  }
}
