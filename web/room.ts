/**
 * Room mode — the multiplayer client: send your Controls intent every
 * frame, render the server's snapshots interpolated between the two
 * newest, and never advance the shared simulation (the authority
 * invariant). Cosmetics are client-local and mapped from the events each
 * snapshot carries.
 */
import type { AudioSfx } from "./audio";
import type { Controls, ShopSlot, Snapshot } from "../shared/protocol";
import { drawGameOver, drawHud, drawWaveBanner, gameOverLines, WaveBanner } from "./hud";
import type { HudView } from "./hud";
import { presentEvents, type CosmeticSink } from "./gamefx";
import { FloatingTexts, ParticleField, Shake } from "./fx";
import { drawShopPanel, drawShopPowerups } from "./shop";
import { assignShipColors, drawWorldLayer } from "./render";
import { LerpBuffer } from "./interpolate";
import type { RoomConnection, SnapshotMsg } from "./ws";
import type { WebSave } from "./storage";

/** True when the snapshot's wave differs from the previously rendered one
 * — the rooms' banner trigger (solo learns waves from events instead). */
export function waveChanged(prev: Snapshot | null, next: Snapshot): boolean {
  return prev === null || prev.wave !== next.wave;
}

/** One plain line per connection status — the reconnect banner and the
 * dropped/rejected messages. Rejections name the readable reason. */
export function statusText(
  status: "connecting" | "reconnecting" | "dropped" | "rejected",
  reason?: "room-full" | "bad-code",
): string {
  switch (status) {
    case "connecting":
      return "Connecting to the room…";
    case "reconnecting":
      return "Connection lost — reconnecting. Your seat is held for 10 seconds.";
    case "dropped":
      return "You were disconnected. The room continues without you — join again to fly.";
    case "rejected":
      return reason === "room-full"
        ? "That room is full — 4 pilots max. Try another code."
        : "No room with that code — check it and try again.";
  }
}

export type RoomAudio = Pick<AudioSfx, "play" | "playExplosion" | "setMuted" | "isMuted">;

export interface RoomGameDeps {
  connection: RoomConnection;
  /** The 4-char room code this client is joined to — surfaced in the HUD
   * so the creator can share it (spec: "room code shown" on entry). */
  roomCode: string;
  ctx: CanvasRenderingContext2D;
  background: HTMLCanvasElement;
  save: WebSave;
  writeSave(save: WebSave): void;
  audio: RoomAudio;
}

export interface RoomInputSource {
  controls(): Controls;
}

export class RoomGame {
  private readonly connection: RoomConnection;
  private readonly roomCode: string;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly background: HTMLCanvasElement;
  private readonly save: WebSave;
  private readonly writeSave: (save: WebSave) => void;
  private readonly audio: RoomAudio;
  private readonly buffer = new LerpBuffer();
  private readonly particles = new ParticleField();
  private readonly shake = new Shake();
  private readonly floats = new FloatingTexts();
  private readonly banner = new WaveBanner();
  private youId: string | null = null;
  private latest: Snapshot | null = null;
  private inputSource: RoomInputSource = {
    controls: () => ({ thrust: false, left: false, right: false, shoot: false, back: false }),
  };

  constructor(deps: RoomGameDeps) {
    this.connection = deps.connection;
    this.roomCode = deps.roomCode;
    this.ctx = deps.ctx;
    this.background = deps.background;
    this.save = deps.save;
    this.writeSave = deps.writeSave;
    this.audio = deps.audio;
  }

  setInputSource(source: RoomInputSource): void {
    this.inputSource = source;
  }

  get snapshot(): Snapshot | null {
    return this.latest;
  }

  /** A server frame arrived: record it, surface its events as cosmetics,
   * flash the banner on a wave change, and persist a fresh high score. */
  onSnapshot(message: SnapshotMsg): void {
    const previous = this.latest;
    this.latest = message;
    this.buffer.push(message, performance.now());
    presentEvents(message.events, this.sink());
    if (waveChanged(previous, message)) this.banner.show(message.wave);
    if (message.phase === "game_over") {
      const mine = message.players.find((p) => p.id === this.youId);
      if (mine && mine.score > this.save.highScore) {
        this.save.highScore = mine.score;
        this.writeSave(this.save);
      }
    }
  }

  onWelcome(you: string, snapshot: Snapshot): void {
    this.youId = you;
    this.buffer.reset();
    // The welcome snapshot carries no event batch (fresh join), so it
    // lands in the buffer directly instead of through onSnapshot.
    this.latest = snapshot;
    this.buffer.push(snapshot, performance.now());
    this.banner.show(snapshot.wave);
  }

  /** One display frame: ship the input intent, then render the
   * interpolated world between the newest snapshots. */
  frame(dtMs: number): void {
    this.connection.sendInput(this.inputSource.controls());

    this.particles.update(dtMs / 1000);
    this.shake.update(dtMs / 1000);
    this.floats.update(dtMs / 1000);
    this.banner.update(dtMs / 1000);

    const snap = this.buffer.sample(performance.now());
    if (snap) this.render(snap);
  }

  /** Shop intents are server-gated — the client only forwards the slot. */
  buySlot(slot: ShopSlot): void {
    this.connection.sendBuy(slot);
  }

  click(x: number, y: number): void {
    this.connection.sendClick(x, y);
  }

  restart(): void {
    this.connection.sendRestart();
  }

  private sink(): CosmeticSink {
    return { particles: this.particles, shake: this.shake, floats: this.floats, audio: this.audio };
  }

  private render(snap: Snapshot): void {
    const view = {
      snap,
      shipColors: assignShipColors(snap.players),
      showNameTags: snap.players.length > 1 || this.youId === null,
      particles: this.particles,
      floats: this.floats,
      now: performance.now() / 1000, // presentation clock (tumble, bank, plume)
    };
    const offset = this.shake.offset();
    drawWorldLayer(this.ctx, view, this.background, offset.x, offset.y);

    const hudView: HudView = {
      players: snap.players,
      youId: this.youId,
      wave: snap.wave,
      credits: snap.economy.credits,
      muted: this.save.muted,
      phase: snap.phase,
      roomCode: this.roomCode,
    };
    drawHud(this.ctx, hudView);
    drawWaveBanner(this.ctx, this.banner);
    if (snap.phase === "game_over") {
      const mine = snap.players.find((p) => p.id === this.youId);
      const isNewHigh = mine !== undefined && mine.score >= this.save.highScore && mine.score > 0;
      drawGameOver(this.ctx, gameOverLines(mine?.score ?? 0, isNewHigh, true));
    }
    drawShopPowerups(this.ctx, snap.economy);
    drawShopPanel(this.ctx, snap.economy);
  }
}
