/**
 * The HUD overlay — web port of hud.py: the top-left line stack with the
 * desktop's hide-zero rules, the audio tags top-right, the centered
 * game-over overlay, and the WAVE n banner flash. Multiplayer extends the
 * stack with the shared credits line and a per-player roster in ship
 * colors. Line building is pure (pinned by tests); the canvas calls are
 * thin and dogfood-verified.
 */
import {
  GAME_OVER_FONT_SIZE,
  GAME_OVER_LINE_STEP,
  HUD_COLOR,
  HUD_FONT_SIZE,
  HUD_LINE_STEP,
  HUD_MARGIN,
  SCREEN_HEIGHT,
  SCREEN_WIDTH,
  WAVE_BANNER_SECONDS,
  type RGB,
} from "../shared/constants";
import type { PlayerSnap, Phase } from "../shared/protocol";
import { assignShipColors } from "./render";
import { fontCss } from "./fonts";

/** One rendered HUD line: text plus the fill color. */
export interface HudLine {
  text: string;
  color: RGB;
}

export interface HudView {
  players: PlayerSnap[];
  youId: string | null;
  wave: number;
  credits: number;
  muted: boolean;
  phase: Phase;
  /** The 4-char room code, shown while connected — the spec's "room code
   * shown" on entry: the creator needs it to invite the second pilot. */
  roomCode?: string | null;
}

/**
 * The top-left line stack, mirroring draw_hud's rules: the score always
 * shows, lives and wave stay hidden while zero. The credits line is new
 * to the web build — the shared ledger is the idle core, so it always
 * shows. The roster (one line per player, ship-colored) rides below.
 */
export function hudLines(view: HudView): HudLine[] {
  const lines: HudLine[] = [];
  const you = view.players.find((player) => player.id === view.youId);
  if (you) {
    lines.push({ text: `Score: ${you.score}`, color: HUD_COLOR });
    if (you.lives > 0) lines.push({ text: `Lives: ${you.lives}`, color: HUD_COLOR });
  }
  if (view.wave > 0) lines.push({ text: `Wave: ${view.wave}`, color: HUD_COLOR });
  lines.push({ text: `Credits: ${view.credits}`, color: HUD_COLOR });
  if (view.roomCode) lines.push({ text: `Room ${view.roomCode}`, color: HUD_COLOR });
  return lines;
}

/** One roster line per player, in their seat color: name, score, lives. */
export function playerRoster(view: HudView): HudLine[] {
  const colors = assignShipColors(view.players);
  return view.players.map((player) => ({
    text: `${player.name || player.id}: ${player.score} pts · ${player.lives} ${
      player.lives === 1 ? "life" : "lives"
    }`,
    color: colors[player.id] as RGB,
  }));
}

/** draw_game_over's line stack. Solo drops the Q-quit line (tab close
 * quits); rooms note that any player may restart. */
export function gameOverLines(score: number, newHigh: boolean, room: boolean): string[] {
  const lines = [`Game over — score ${score}`];
  if (newHigh) lines.push("New high score!");
  lines.push(room ? "press R to restart — any player can" : "press R to restart");
  return lines;
}

/**
 * WaveBanner, ported from hud.py's class: the house dt-timer pattern — a
 * float decremented every frame, visible while positive, alpha fading out
 * over the duration.
 */
export class WaveBanner {
  readonly duration = WAVE_BANNER_SECONDS;
  timer = 0;
  wave = 1;

  show(wave: number): void {
    this.wave = wave;
    this.timer = this.duration;
  }

  update(dt: number): void {
    if (this.timer > 0) this.timer = Math.max(0, this.timer - dt);
  }

  get visible(): boolean {
    return this.timer > 0;
  }

  /** The flash's alpha fraction (timer/duration), for the canvas draw. */
  get alpha(): number {
    return this.duration > 0 ? this.timer / this.duration : 0;
  }
}

/** The HUD overlay: line stack top-left, roster under it, MUTED top-right. */
export function drawHud(ctx: CanvasRenderingContext2D, view: HudView): void {
  ctx.font = fontCss(HUD_FONT_SIZE);
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  const stack = [...hudLines(view), ...playerRoster(view)];
  stack.forEach((line, row) => {
    ctx.fillStyle = `rgb(${line.color[0]}, ${line.color[1]}, ${line.color[2]})`;
    ctx.fillText(line.text, HUD_MARGIN, HUD_MARGIN + row * HUD_LINE_STEP);
  });
  if (view.muted) {
    ctx.textAlign = "right";
    ctx.fillText("MUTED", SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN);
    ctx.textAlign = "left";
  }
}

/** The centered game-over overlay (draw_game_over). */
export function drawGameOver(ctx: CanvasRenderingContext2D, lines: string[]): void {
  ctx.font = fontCss(GAME_OVER_FONT_SIZE);
  ctx.fillStyle = `rgb(${HUD_COLOR[0]}, ${HUD_COLOR[1]}, ${HUD_COLOR[2]})`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const height = lines.length * GAME_OVER_LINE_STEP;
  const top = SCREEN_HEIGHT / 2 - height / 2;
  lines.forEach((text, row) => {
    ctx.fillText(text, SCREEN_WIDTH / 2, top + (row + 0.5) * GAME_OVER_LINE_STEP);
  });
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
}

/** The WAVE n flash: centered, upper third, fading out (WaveBanner.draw). */
export function drawWaveBanner(ctx: CanvasRenderingContext2D, banner: WaveBanner): void {
  if (!banner.visible) return;
  ctx.font = fontCss(GAME_OVER_FONT_SIZE);
  ctx.fillStyle = `rgb(${HUD_COLOR[0]}, ${HUD_COLOR[1]}, ${HUD_COLOR[2]})`;
  ctx.globalAlpha = banner.alpha;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(`WAVE ${banner.wave}`, SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3);
  ctx.globalAlpha = 1;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
}
