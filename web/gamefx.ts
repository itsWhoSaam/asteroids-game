/**
 * GameEvent → client cosmetics — the wiring main.py does inline at each
 * destruction site, relocated here because presentation leaves the logic
 * (spec: Fidelity rules). Solo and room modes share this mapper; only the
 * wave banner differs (rooms learn waves from snapshots, solo from the
 * event stream).
 */
import type { GameEvent } from "../shared/protocol";
import { ASTEROID_MIN_RADIUS } from "../shared/constants";
import type { ParticleField, Shake, FloatingTexts } from "./fx";
import type { SfxName } from "./audio";

/** Everything the presentation layer needs to react to one event batch. */
export interface CosmeticSink {
  readonly particles: ParticleField;
  readonly shake: Shake;
  readonly floats: FloatingTexts;
  readonly audio: { play(name: SfxName): void; playExplosion(size: 1 | 2 | 3): void };
}

/** Explosion debris size follows the rock size — the burst-count base the
 * desktop passes at each split site. Tiers count in ASTEROID_MIN_RADIUS
 * units (radius / ASTEROID_MIN_RADIUS). */
function debrisRadius(size: 1 | 2 | 3): number {
  return ASTEROID_MIN_RADIUS * size;
}

/** Apply one sim event batch to cosmetics and sound. Pure with respect to
 * the sim — it touches only the sink. */
export function presentEvents(events: readonly GameEvent[], sink: CosmeticSink): void {
  for (const event of events) {
    switch (event.k) {
      case "shoot":
        sink.audio.play("shoot");
        break;
      case "explosion":
        sink.particles.burst(event.x, event.y, debrisRadius(event.size));
        sink.shake.kick(event.size * 2);
        sink.audio.playExplosion(event.size);
        break;
      case "burst":
        sink.particles.burst(event.x, event.y, event.radius);
        break;
      case "playerHit":
        sink.particles.burst(event.x, event.y, 40, 1.4);
        sink.shake.kick(8);
        sink.audio.playExplosion(3);
        break;
      case "pickup":
        // Desktop plays the chirp; the pickup's position isn't on the
        // event, so no float here — mint events carry their own.
        sink.audio.play("powerup");
        break;
      case "waveStarted":
        // The banner lives with the mode (solo owns one; rooms derive
        // waves from snapshots).
        break;
      case "gameOver":
        sink.audio.play("game_over");
        break;
      case "mint":
        sink.floats.spawn(event.x, event.y, `+${Math.trunc(event.amount)} cr`, "#ffd47f");
        break;
      case "purchase":
        // Ledger bookkeeping; the HUD already reflects it.
        break;
    }
  }
}
