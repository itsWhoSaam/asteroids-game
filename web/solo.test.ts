/**
 * Tests for solo mode — the local fixed-dt loop over the shared sim with
 * autosave, high-score persistence, and the restart gate. Rendering is a
 * no-op stub; the sim and persistence seams are the real ones.
 */
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_SAVE, type WebSave } from "./storage";
import { SoloGame, type SoloAudio, type SoloInputSource } from "./solo";
import type { Controls } from "../shared/protocol";

function stubCtx(): CanvasRenderingContext2D {
  const noop = () => undefined;
  return {
    fillRect: noop,
    beginPath: noop,
    arc: noop,
    fill: noop,
    stroke: noop,
    moveTo: noop,
    lineTo: noop,
    closePath: noop,
    save: noop,
    restore: noop,
    translate: noop,
    drawImage: noop,
    fillText: noop,
  } as unknown as CanvasRenderingContext2D;
}

function makeGame(save = structuredClone(DEFAULT_SAVE) as WebSave) {
  const writeSave = vi.fn();
  const audio: SoloAudio = {
    play: vi.fn(),
    playExplosion: vi.fn(),
    setMuted: vi.fn(),
  };
  const game = new SoloGame({
    seed: 7,
    playerName: "Tester",
    save,
    writeSave,
    ctx: stubCtx(),
    background: {} as HTMLCanvasElement,
    audio,
  });
  return { game, save, writeSave, audio };
}

/** A scripted input source for the tests. */
function scriptedInput(controls: Controls): SoloInputSource {
  return { controls: () => controls };
}

const THRUST: Controls = { thrust: true, left: false, right: false, shoot: false, back: false };

/** Warm the spawn timer until at least one asteroid exists (~1s). */
function warmSpawns(game: SoloGame): void {
  for (let i = 0; i < 70 && game.world.asteroids.length === 0; i += 1) {
    game.frame(16.7);
  }
}

/** Stage a lethal collision: one life left, no grace, a rock on the ship.
 * The rock moves to the SHIP (the Python tests' pattern) — teleporting the
 * ship to a freshly spawned rock would park it beyond the wrap margin, and
 * the ship-only wrap would hand it to the opposite edge before the sweep. */
function stageDeath(game: SoloGame): void {
  warmSpawns(game);
  const player = game.world.players.solo;
  const rock = game.world.asteroids[0];
  if (!player || !rock) throw new Error("warmup failed to produce a ship and a rock");
  player.score = 500;
  player.lives = 1;
  player.invulnerabilityTimer = 0;
  rock.x = player.x;
  rock.y = player.y;
}

describe("SoloGame construction", () => {
  it("creates a wave-1 world with one named solo seat", () => {
    const { game } = makeGame();
    expect(game.world.wave).toBe(1);
    expect(game.world.phase).toBe("playing");
    expect(game.world.players.solo?.name).toBe("Tester");
  });

  it("applies the mute flag from the save at construction", () => {
    const save = { ...structuredClone(DEFAULT_SAVE), muted: true } as WebSave;
    const { audio } = makeGame(save);
    expect(audio.setMuted).toHaveBeenCalledWith(true);
  });

  it("seeds the fresh ledger from the persisted solo save", () => {
    const save = {
      ...structuredClone(DEFAULT_SAVE),
      solo: { credits: 250, levels: { drone: 2 }, powerupUses: { nuke: 1 } },
    } as WebSave;
    const { game } = makeGame(save);
    expect(game.world.economy.credits).toBe(250);
    expect(game.world.economy.levels.drone).toBe(2);
    expect(game.world.economy.powerupUses.nuke).toBe(1);
  });
});

describe("SoloGame.frame — the fixed-dt local loop", () => {
  it("advances the sim: idle frames spawn asteroids from the field", () => {
    const { game } = makeGame();
    warmSpawns(game);
    expect(game.world.asteroids.length).toBeGreaterThan(0);
  });

  it("moves the ship with thrust input", () => {
    const { game } = makeGame();
    const startY = game.world.players.solo?.y as number;
    game.setInputSource(scriptedInput(THRUST));
    for (let i = 0; i < 30; i += 1) game.frame(16.7);
    // UP is (0, 1) in this sim's coordinate convention: thrust at
    // rotation 0 walks the ship down the canvas.
    expect((game.world.players.solo?.y as number) > startY).toBe(true);
  });

  it("autosaves after five seconds of play", () => {
    const { game, writeSave } = makeGame();
    for (let i = 0; i < 302; i += 1) game.frame(16.7); // ~5.04s
    expect(writeSave).toHaveBeenCalledTimes(1);
  });

  it("bounds catch-up like the server tick does (a huge frame is capped)", () => {
    const { game } = makeGame();
    game.frame(10_000); // a stalled tab returning — must not tunnel the sim
    expect(game.world.asteroids.length).toBeLessThanOrEqual(1);
  });
});

describe("SoloGame shop and click intents", () => {
  it("buys an upgrade through the shared sim's own affordability gate", () => {
    const save = {
      ...structuredClone(DEFAULT_SAVE),
      solo: { credits: 10_000, levels: {}, powerupUses: {} },
    } as WebSave;
    const { game } = makeGame(save);
    game.buySlot(1);
    expect(game.world.economy.levels.nanoblade).toBe(1);
    expect(game.world.economy.credits).toBeLessThan(10_000);
  });

  it("clicks empty space as a no-op", () => {
    const { game } = makeGame();
    expect(() => game.click(10, 10)).not.toThrow();
  });
});

describe("SoloGame game over and restart", () => {
  it("persists the high score and save at game over", () => {
    const { game, save, writeSave } = makeGame();
    stageDeath(game);
    game.frame(16.7);
    expect(game.world.phase).toBe("game_over");
    expect(save.highScore).toBe(500);
    expect(writeSave).toHaveBeenCalled();
  });

  it("ignores R mid-run", () => {
    const { game } = makeGame();
    const worldBefore = game.world;
    game.restart();
    expect(game.world).toBe(worldBefore);
    expect(game.world.phase).toBe("playing");
  });

  it("restarts from game over into a fresh wave-1 world with the same seat", () => {
    const { game } = makeGame();
    stageDeath(game);
    game.frame(16.7);
    expect(game.world.phase).toBe("game_over");
    const dead = game.world;
    game.restart();
    expect(game.world).not.toBe(dead);
    expect(game.world.wave).toBe(1);
    expect(game.world.phase).toBe("playing");
    expect(game.world.players.solo?.name).toBe("Tester");
  });
});
