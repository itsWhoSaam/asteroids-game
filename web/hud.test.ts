/**
 * Tests for the HUD's pure seams — line construction with the desktop's
 * hide-zero rules, the per-player roster colors, the game-over stack, and
 * the WaveBanner dt-timer. Canvas draws are dogfood-verified.
 */
import { describe, expect, it } from "vitest";
import { PALETTE } from "../shared/constants";
import type { PlayerSnap } from "../shared/protocol";
import { assignShipColors } from "./render";
import { gameOverLines, hudLines, playerRoster, WaveBanner, type HudView } from "./hud";

function player(id: string, overrides: Partial<PlayerSnap> = {}): PlayerSnap {
  return {
    id,
    name: `P${id}`,
    x: 0,
    y: 0,
    vx: 0,
    vy: 0,
    rotation: 0,
    lives: 3,
    score: 0,
    invulnTimer: 0,
    shieldHits: 0,
    ...overrides,
  };
}

function view(overrides: Partial<HudView> = {}): HudView {
  return {
    players: [],
    youId: null,
    wave: 0,
    credits: 0,
    muted: false,
    phase: "playing",
    ...overrides,
  };
}

describe("hudLines", () => {
  it("always shows the score and hides zero lives and wave", () => {
    const lines = hudLines(view({ players: [player("a", { lives: 0 })], youId: "a", wave: 0 }));
    expect(lines.map((line) => line.text)).toEqual(["Score: 0", "Credits: 0"]);
  });

  it("shows lives and wave once nonzero, with the credits line", () => {
    const lines = hudLines(view({ players: [player("a", { score: 120, lives: 2 })], youId: "a", wave: 3, credits: 45 }));
    expect(lines.map((line) => line.text)).toEqual(["Score: 120", "Lives: 2", "Wave: 3", "Credits: 45"]);
  });

  it("is empty of player lines when you have no seat yet", () => {
    const lines = hudLines(view({ players: [player("a")], youId: null, wave: 1 }));
    expect(lines.map((line) => line.text)).toEqual(["Wave: 1", "Credits: 0"]);
  });

  it("shows the room code line only while one is set", () => {
    const withCode = hudLines(view({ players: [player("a")], youId: "a", wave: 1, roomCode: "AB2F" }));
    expect(withCode.map((line) => line.text)).toEqual([
      "Score: 0",
      "Lives: 3",
      "Wave: 1",
      "Credits: 0",
      "Room AB2F",
    ]);
    const withoutCode = hudLines(view({ players: [player("a")], youId: "a", wave: 1 }));
    expect(withoutCode.map((line) => line.text)).toEqual(["Score: 0", "Lives: 3", "Wave: 1", "Credits: 0"]);
  });
});

describe("playerRoster", () => {
  it("labels every player and colors lines by seat", () => {
    const players = [player("b", { name: "Bee", score: 30, lives: 1 }), player("a", { name: "Ay", score: 10 })];
    const roster = playerRoster(view({ players }));
    const colors = assignShipColors(players);
    expect(roster[0]?.text).toBe("Bee: 30 pts · 1 life");
    expect(roster[1]?.text).toBe("Ay: 10 pts · 3 lives");
    expect(roster[0]?.color).toEqual(colors.b);
    expect(roster[1]?.color).toEqual(colors.a);
  });

  it("falls back to the id when a name is blank", () => {
    const roster = playerRoster(view({ players: [player("a", { name: "" })] }));
    expect(roster[0]?.text).toContain("a:");
  });

  it("never colors two players identically in a full room", () => {
    const players = ["a", "b", "c", "d"].map((id) => player(id));
    const roster = playerRoster(view({ players }));
    const seen = new Set(roster.map((line) => line.color.join(",")));
    expect(seen.size).toBe(players.length);
  });
});

describe("gameOverLines", () => {
  it("matches the desktop stack, with the restart line swapped for rooms", () => {
    expect(gameOverLines(500, false, false)).toEqual(["Game over — score 500", "press R to restart"]);
    expect(gameOverLines(500, true, false)).toEqual([
      "Game over — score 500",
      "New high score!",
      "press R to restart",
    ]);
    expect(gameOverLines(500, false, true)).toEqual([
      "Game over — score 500",
      "press R to restart — any player can",
    ]);
  });
});

describe("WaveBanner (hud.py's dt-timer)", () => {
  it("arms on show, fades by dt, and stops at zero", () => {
    const banner = new WaveBanner();
    expect(banner.visible).toBe(false);
    banner.show(2);
    expect(banner.visible).toBe(true);
    expect(banner.wave).toBe(2);
    expect(banner.alpha).toBeCloseTo(1);
    banner.update(banner.duration / 2);
    expect(banner.visible).toBe(true);
    expect(banner.alpha).toBeCloseTo(0.5);
    banner.update(banner.duration);
    expect(banner.visible).toBe(false);
    expect(banner.timer).toBe(0);
  });

  it("ignores dt while hidden", () => {
    const banner = new WaveBanner();
    banner.update(10);
    expect(banner.visible).toBe(false);
  });
});

describe("seat colors come from the shared palette", () => {
  it("player one wears the desktop ship color", () => {
    const roster = playerRoster(view({ players: [player("a")] }));
    expect(roster[0]?.color).toEqual(PALETTE.ship);
  });
});
