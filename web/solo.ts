/**
 * Solo mode — the shared simulation runs in the browser with a
 * session-seeded RNG and zero server dependency (spec: web client).
 * The loop is the server room tick's twin: fixed 1/60 step behind a
 * MAX_DT-bounded accumulator, presentation drawn from the sim's own
 * snapshot each frame.
 */
import { MAX_DT, PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH } from "../shared/constants";
import type { GameEvent } from "../shared/protocol";
import { addPlayer, buy, clickAt, newWorld, snapshot, step } from "../shared/sim";
import type { World } from "../shared/sim";
import type { Controls, ShopSlot } from "../shared/protocol";
import type { AudioSfx } from "./audio";
import { drawGameOver, drawHud, drawWaveBanner, gameOverLines, WaveBanner } from "./hud";
import type { HudView } from "./hud";
import { presentEvents, type CosmeticSink } from "./gamefx";
import { FloatingTexts, ParticleField, Shake } from "./fx";
import { buildBackground, drawWorldLayer } from "./render";
import { drawShopPanel, drawShopPowerups } from "./shop";
import type { WebSave } from "./storage";

const STEP = 1 / 60;
const AUTOSAVE_SECONDS = 5;
const SOLO_ID = "solo";

/** The pieces of AudioSfx solo mode touches — injectable for tests. */
export type SoloAudio = Pick<AudioSfx, "play" | "playExplosion" | "setMuted">;

export interface SoloGameOpts {
  seed: number;
  playerName: string;
  save: WebSave;
  /** Persistence seam: called with the current save on every write. */
  writeSave(save: WebSave): void;
  ctx: CanvasRenderingContext2D;
  background: HTMLCanvasElement;
  audio: SoloAudio;
}

export interface SoloInputSource {
  controls(): Controls;
}

export class SoloGame {
  world: World;
  private readonly save: WebSave;
  private readonly writeSave: (save: WebSave) => void;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly background: HTMLCanvasElement;
  private readonly audio: SoloAudio;
  private readonly particles = new ParticleField();
  private readonly shake = new Shake();
  private readonly floats = new FloatingTexts();
  private readonly banner = new WaveBanner();
  private readonly seed: number;
  private readonly playerName_: string;
  private restartCount = 0;
  private lastRunWasHigh = false;
  private inputSource: SoloInputSource = {
    controls: () => ({ thrust: false, left: false, right: false, shoot: false, back: false }),
  };
  private accumulator = 0;
  private autosaveCounter = 0;

  constructor(opts: SoloGameOpts) {
    this.world = newWorld(opts.seed);
    this.seed = opts.seed;
    this.playerName_ = opts.playerName || "You";
    addPlayer(this.world, SOLO_ID, this.playerName_);
    this.save = opts.save;
    this.writeSave = opts.writeSave;
    this.ctx = opts.ctx;
    this.background = opts.background;
    this.audio = opts.audio;
    this.audio.setMuted(this.save.muted);
    // Solo progression lives in the save; seed the fresh world's ledger
    // from it so a reload continues where the last session left off.
    this.world.economy.credits = this.save.solo.credits;
    Object.assign(this.world.economy.levels, this.save.solo.levels);
    Object.assign(this.world.economy.powerupUses, this.save.solo.powerupUses);
  }

  /** Wire the live keyboard capture; called by the entry after attach. */
  setInputSource(source: SoloInputSource): void {
    this.inputSource = source;
  }

  /** A shop slot press — the sim's own gate decides affordability. */
  buySlot(slot: ShopSlot): void {
    this.drain(buy(this.world, slot));
  }

  /** Click-to-chip: the shared sim resolves the target under the point. */
  click(x: number, y: number): void {
    this.drain(clickAt(this.world, x, y));
  }

  /** Desktop R: a full restart from the game-over screen. */
  restart(): void {
    if (this.world.phase !== "game_over") return;
    this.restartCount += 1;
    const fresh = newWorld((this.seed + this.restartCount) | 0);
    addPlayer(fresh, SOLO_ID, this.playerName_);
    this.world = fresh;
  }

  /** Advance one display frame: fixed-dt sim steps behind the
   * accumulator, then cosmetics, then a full redraw. */
  frame(dtMs: number): void {
    const dt = Math.min(dtMs / 1000, MAX_DT);
    this.accumulator = Math.min(this.accumulator + dt, MAX_DT);
    while (this.accumulator >= STEP) {
      const events = step(this.world, STEP, { [SOLO_ID]: this.inputSource.controls() });
      this.drain(events);
      this.accumulator -= STEP;
    }

    this.particles.update(dt);
    this.shake.update(dt);
    this.floats.update(dt);
    this.banner.update(dt);

    this.autosaveCounter += dt;
    if (this.autosaveCounter >= AUTOSAVE_SECONDS) {
      this.autosaveCounter = 0;
      this.syncSave();
    }

    this.render();
  }

  /** Flush the ledger into the save — on autosave, game over, and page
   * hide (wired by the entry). */
  syncSave(): void {
    this.save.solo.credits = this.world.economy.credits;
    this.save.solo.levels = { ...this.world.economy.levels };
    this.save.solo.powerupUses = { ...this.world.economy.powerupUses };
    this.writeSave(this.save);
  }

  private drain(events: GameEvent[]): void {
    presentEvents(events, this.sink());
    for (const event of events) {
      if (event.k === "waveStarted") this.banner.show(event.wave);
      if (event.k === "gameOver") this.onGameOver();
    }
  }

  private sink(): CosmeticSink {
    return { particles: this.particles, shake: this.shake, floats: this.floats, audio: this.audio };
  }

  private onGameOver(): void {
    const score = this.runScore();
    this.lastRunWasHigh = score > this.save.highScore && score > 0;
    if (score > this.save.highScore) {
      this.save.highScore = score;
    }
    this.syncSave();
  }

  private runScore(): number {
    return this.world.players[SOLO_ID]?.score ?? 0;
  }

  private render(): void {
    const view = {
      snap: snapshot(this.world),
      shipColors: { [SOLO_ID]: PALETTE.ship },
      showNameTags: false, // one ship — no tags needed
      particles: this.particles,
      floats: this.floats,
      now: performance.now() / 1000, // presentation clock (tumble, bank, plume)
    };
    const offset = this.shake.offset();
    drawWorldLayer(this.ctx, view, this.background, offset.x, offset.y);

    const hudView: HudView = {
      players: view.snap.players,
      youId: SOLO_ID,
      wave: this.world.wave,
      credits: this.world.economy.credits,
      muted: this.save.muted,
      phase: this.world.phase,
    };
    drawHud(this.ctx, hudView);
    drawWaveBanner(this.ctx, this.banner);
    if (this.world.phase === "game_over") {
      drawGameOver(this.ctx, gameOverLines(this.runScore(), this.lastRunWasHigh, false));
    }
    drawShopPowerups(this.ctx, this.world.economy);
    drawShopPanel(this.ctx, this.world.economy);
  }
}

/** Build the pre-rendered background once per game session. */
export function makeBackground(): HTMLCanvasElement {
  return buildBackground(SCREEN_WIDTH, SCREEN_HEIGHT);
}
