/**
 * Simulation invariants, each pinned to the Python source's semantics
 * (main.py, player.py, asteroid.py, asteroidfield.py, economy.py, drones.py,
 * powerups.py, game.py). Seeds are arbitrary but fixed — mulberry32 is
 * deterministic, so every assertion holds identically across runs.
 */
import { describe, expect, it } from "vitest";
import { POWERUPS } from "./constants";
import {
  addPlayer,
  buy,
  chipThreshold,
  clickAt,
  clickDamage,
  dropsPowerup,
  incomeMultiplier,
  newWorld,
  pickPowerupType,
  pointsFor,
  powerupPrice,
  removePlayer,
  requestRestart,
  step,
  upgradeCost,
  waveParams,
} from "./sim";
import type { AsteroidState, World } from "./sim";
import type { Controls, GameEvent } from "./protocol";

const DT = 1 / 60;

function must<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`${what} missing`);
  return value;
}

const NO_CONTROLS: Controls = {
  thrust: false,
  back: false,
  left: false,
  right: false,
  shoot: false,
};

/** Solo-world inputs, keyed to the single seated player id. */
function controls(partial: Partial<Controls>): Record<string, Controls> {
  return { p1: { ...NO_CONTROLS, ...partial } };
}

/** A world with one seated player. */
function soloWorld(seed = 1234): World {
  const w = newWorld(seed);
  addPlayer(w, "p1", "Player 1");
  return w;
}

/** Hand-place an asteroid at a known position/velocity (test setup only). */
function placeAsteroid(w: World, x: number, y: number, vx: number, vy: number, radius: number): AsteroidState {
  const a: AsteroidState = { id: w.nextEntityId++, x, y, vx, vy, radius, chipDamage: 0 };
  w.asteroids.push(a);
  return a;
}

/** Hand-place a shot already in contact with something (test setup only). */
function injectShot(w: World, x: number, y: number, owner: string | null): void {
  w.shots.push({ id: w.nextEntityId++, x, y, vx: 0, vy: 0, owner });
}

describe("newWorld / players", () => {
  it("starts at wave 1, playing, empty field, zeroed ledger", () => {
    const w = newWorld(42);
    expect(w.wave).toBe(1);
    expect(w.phase).toBe("playing");
    expect(w.asteroids).toHaveLength(0);
    expect(w.shots).toHaveLength(0);
    expect(w.powerups).toHaveLength(0);
    expect(w.economy.credits).toBe(0);
    expect(w.economy.levels.nanoblade).toBe(0);
  });

  it("seats a player at the screen center with full lives and the grace window", () => {
    const w = soloWorld();
    const p = must(w.players.p1, "p1");
    expect(p.x).toBe(640); // SCREEN_WIDTH / 2
    expect(p.y).toBe(360); // SCREEN_HEIGHT / 2
    expect(p.lives).toBe(3); // PLAYER_START_LIVES
    expect(p.invulnerabilityTimer).toBe(2.0); // PLAYER_INVULNERABILITY_SECONDS
    expect(p.score).toBe(0);
  });

  it("removePlayer drops the ship; the room continues", () => {
    const w = soloWorld();
    addPlayer(w, "p2", "Player 2");
    removePlayer(w, "p2");
    expect(w.players.p2).toBeUndefined();
    expect(w.players.p1).toBeDefined();
  });
});

describe("scoring by size tier", () => {
  it("pays 20/50/100 for large/medium/small", () => {
    expect(pointsFor(60)).toBe(20);
    expect(pointsFor(40)).toBe(50);
    expect(pointsFor(20)).toBe(100);
  });

  it("band boundaries follow hud.points_for", () => {
    expect(pointsFor(70)).toBe(20); // 3.5x → large
    expect(pointsFor(41)).toBe(50); // 2.05x → medium
  });
});

describe("split geometry", () => {
  it("a shot kill splits a large rock into two medium children at ×1.2 the rotated parent velocity", () => {
    const w = soloWorld(2024);
    const parent = placeAsteroid(w, 400, 300, 100, 0, 60);
    injectShot(w, 401, 300, "p1");
    step(w, DT, {});
    expect(w.asteroids).toHaveLength(2);
    for (const child of w.asteroids) {
      expect(child.radius).toBe(40); // 60 − ASTEROID_MIN_RADIUS
      expect(Math.hypot(child.vx, child.vy)).toBeCloseTo(120, 6); // |100| × 1.2
      // Children spawn at the parent's (moved) position.
      expect(child.x).toBeCloseTo(400 + 100 * DT, 6);
      expect(child.y).toBe(300);
      // ±(20–50°) around the parent's velocity direction (+x).
      const angle = (Math.atan2(child.vy, child.vx) * 180) / Math.PI;
      const parentAngle = (Math.atan2(parent.vy, parent.vx) * 180) / Math.PI;
      const spread = Math.abs(angle - parentAngle);
      expect(spread).toBeGreaterThanOrEqual(19.999);
      expect(spread).toBeLessThanOrEqual(50.001);
    }
  });

  it("children born mid-step wait for the next tick to move", () => {
    const w = soloWorld(2024);
    placeAsteroid(w, 400, 300, 100, 0, 60);
    injectShot(w, 401, 300, "p1");
    step(w, DT, {});
    for (const child of w.asteroids) {
      // Exactly the parent's post-move position — no additional motion.
      expect(child.x).toBeCloseTo(400 + 100 * DT, 6);
      expect(child.y).toBe(300);
    }
  });

  it("a small rock vanishes without children", () => {
    const w = soloWorld(2024);
    placeAsteroid(w, 400, 300, 100, 0, 20);
    injectShot(w, 401, 300, "p1");
    const events = step(w, DT, {});
    expect(w.asteroids).toHaveLength(0);
    expect(events.filter((e) => e.k === "explosion")).toHaveLength(1);
  });
});

describe("wave params (asteroidfield.wave_params)", () => {
  it("tightens the cadence ×0.9 per wave", () => {
    expect(waveParams(1).spawnInterval).toBeCloseTo(0.8, 10);
    expect(waveParams(2).spawnInterval).toBeCloseTo(0.72, 10);
    expect(waveParams(6).spawnInterval).toBeCloseTo(0.472392, 5);
    expect(waveParams(7).spawnInterval).toBeCloseTo(0.4251528, 5);
  });

  it("never drops below the 0.3s floor", () => {
    expect(waveParams(30).spawnInterval).toBe(0.3);
  });

  it("climbs the speed band +10/+15 per wave", () => {
    expect(waveParams(1).speedMin).toBe(40);
    expect(waveParams(1).speedMax).toBe(100);
    expect(waveParams(2).speedMin).toBe(50);
    expect(waveParams(2).speedMax).toBe(115);
    expect(waveParams(11).speedMin).toBe(140);
    expect(waveParams(11).speedMax).toBe(250);
  });
});

describe("wave advance guard", () => {
  it("advances only after a populated wave is cleared", () => {
    const w = soloWorld(1);
    w.field.spawnedThisWave = 1;
    placeAsteroid(w, 200, 200, 0, 0, 60);
    step(w, DT, {});
    expect(w.wave).toBe(1); // rock still present
    w.asteroids.length = 0;
    const events = step(w, DT, {});
    expect(w.wave).toBe(2);
    expect(events.filter((e) => e.k === "waveStarted")).toEqual([{ k: "waveStarted", wave: 2 }]);
    // The populated guard resets: an empty field no longer advances.
    step(w, DT, {});
    expect(w.wave).toBe(2);
  });

  it("never advances an unpopulated field (game start / restart)", () => {
    const w = newWorld(1); // no players; field empty and unpopulated
    for (let i = 0; i < 600; i++) step(w, DT, {});
    expect(w.wave).toBe(1);
  });
});

describe("economy cost curves and purchase gating", () => {
  it("costs follow base × growth**level", () => {
    const w = newWorld(1);
    expect(upgradeCost(w.economy, "nanoblade")).toBe(10.0);
    w.economy.levels.nanoblade = 1;
    expect(upgradeCost(w.economy, "nanoblade")).toBe(17.5); // 10 × 1.75
  });

  it("gates unaffordable purchases (no ledger change, no event)", () => {
    const w = newWorld(1);
    w.economy.credits = 9;
    expect(buy(w, 1)).toEqual([]);
    expect(w.economy.credits).toBe(9);
    expect(w.economy.levels.nanoblade).toBe(0);
  });

  it("charges the ledger and bumps the level on an affordable buy", () => {
    const w = newWorld(1);
    w.economy.credits = 10;
    expect(buy(w, 1)).toEqual([{ k: "purchase", what: "nanoblade" }]);
    expect(w.economy.credits).toBe(0);
    expect(w.economy.levels.nanoblade).toBe(1);
  });

  it("powerup prices escalate ×1.25 per use", () => {
    const w = newWorld(1);
    expect(powerupPrice(w.economy, "gold_rush")).toBe(400);
    w.economy.powerupUses.gold_rush = 1;
    expect(powerupPrice(w.economy, "gold_rush")).toBeCloseTo(500, 6);
    w.economy.powerupUses.gold_rush = 2;
    expect(powerupPrice(w.economy, "gold_rush")).toBeCloseTo(625, 6);
  });

  it("gold rush charges 400 and arms its 15s timer", () => {
    const w = newWorld(1);
    w.economy.credits = 400;
    expect(buy(w, 7)).toEqual([{ k: "purchase", what: "gold_rush" }]);
    expect(w.economy.credits).toBe(0);
    expect(w.economy.powerupTimers.gold_rush).toBe(15.0);
  });

  it("the nuke is instant (duration 0)", () => {
    expect(POWERUPS.nuke.duration).toBe(0.0);
  });
});

describe("income and click-damage seams", () => {
  it("income multiplier compounds ×1.15 per level", () => {
    const w = newWorld(1);
    expect(incomeMultiplier(w.economy)).toBe(1);
    w.economy.levels.income = 2;
    expect(incomeMultiplier(w.economy)).toBeCloseTo(1.3225, 10); // 1.15²
  });

  it("gold rush multiplies the whole income seam, stacking with Income levels", () => {
    const w = newWorld(1);
    w.economy.levels.income = 1;
    w.economy.credits = 400;
    buy(w, 7);
    expect(incomeMultiplier(w.economy)).toBeCloseTo(1.15 * 5, 10);
  });

  it("mint payouts ride the income seam", () => {
    const w = soloWorld(1);
    w.economy.levels.income = 1;
    placeAsteroid(w, 200, 200, 0, 0, 20); // small rock
    injectShot(w, 200, 200, "p1");
    step(w, DT, {});
    expect(w.economy.credits).toBeCloseTo(100 * 1.15, 6);
    expect(must(w.players.p1, "p1").score).toBe(100); // score is NOT scaled by income
  });

  it("click damage: ×1.8 per Nanoblade level, ×10 while Overdrive runs", () => {
    const w = newWorld(1);
    expect(clickDamage(w.economy)).toBe(1.0);
    w.economy.levels.nanoblade = 2;
    expect(clickDamage(w.economy)).toBeCloseTo(3.24, 10);
    w.economy.powerupTimers.overdrive = 10.0;
    expect(clickDamage(w.economy)).toBeCloseTo(32.4, 10);
  });
});

describe("chip thresholds (asteroid.chip_threshold)", () => {
  it("costs 3 HP per size tier", () => {
    const w = newWorld(1);
    const small = placeAsteroid(w, 0, 0, 0, 0, 20);
    const medium = placeAsteroid(w, 100, 0, 0, 0, 40);
    const large = placeAsteroid(w, 200, 0, 0, 0, 60);
    expect(chipThreshold(small)).toBeCloseTo(3.0);
    expect(chipThreshold(medium)).toBeCloseTo(6.0);
    expect(chipThreshold(large)).toBeCloseTo(9.0);
  });
});

describe("click-to-chip", () => {
  it("chips accrue, and crossing the threshold dies through the normal split path", () => {
    const w = soloWorld(1);
    placeAsteroid(w, 400, 300, 0, 0, 60); // large: threshold 9
    for (let i = 0; i < 8; i++) clickAt(w, 400, 300);
    expect(w.asteroids).toHaveLength(1);
    expect(w.asteroids[0]?.chipDamage).toBeCloseTo(8.0, 6);
    clickAt(w, 400, 300); // 9th click crosses 9.0
    expect(w.asteroids).toHaveLength(2); // two medium children
    expect(w.economy.credits).toBeCloseTo(20, 6); // minted in the same call
    // Chip kills mint credits but never score.
    expect(must(w.players.p1, "p1").score).toBe(0);
  });

  it("a click on empty space changes nothing", () => {
    const w = soloWorld(1);
    placeAsteroid(w, 400, 300, 0, 0, 60);
    expect(clickAt(w, 5, 5)).toEqual([]);
    expect(w.asteroids).toHaveLength(1);
  });

  it("nanoblade levels cut the clicks-to-kill", () => {
    const w = soloWorld(1);
    placeAsteroid(w, 400, 300, 0, 0, 60); // threshold 9
    w.economy.levels.nanoblade = 2; // damage 3.24/click
    const events = clickAt(w, 400, 300);
    expect(w.asteroids[0]?.chipDamage).toBeCloseTo(3.24, 6);
    expect(events).toEqual([]); // not dead yet
  });
});

describe("drop rules (powerups.py)", () => {
  it("small rocks never drop", () => {
    expect(dropsPowerup(20, 0.0)).toBe(false);
  });

  it("the boundary roll sits on the no-drop side", () => {
    expect(dropsPowerup(40, 0.15)).toBe(false);
    expect(dropsPowerup(40, 0.149999)).toBe(true);
  });

  it("maps rolls evenly across shield/rapid/triple", () => {
    expect(pickPowerupType(0.0)).toBe("shield");
    expect(pickPowerupType(0.34)).toBe("rapid");
    expect(pickPowerupType(0.66)).toBe("rapid");
    expect(pickPowerupType(0.67)).toBe("triple");
    expect(pickPowerupType(1.0)).toBe("triple"); // clamped
  });
});

describe("player update (player.py)", () => {
  it("turns 300°/s and thrusts 200 px/s along the facing", () => {
    const w = soloWorld(7);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    for (let i = 0; i < 18; i++) step(w, DT, controls({ right: true }));
    expect(p.rotation).toBeCloseTo(90, 6); // 300 × 0.5s
    for (let i = 0; i < 60; i++) step(w, DT, controls({ thrust: true }));
    // (0,1) rotated +90° is (−1, 0) — pygame's rotate matrix.
    expect(p.x).toBeCloseTo(640 - 200, 1);
    expect(p.y).toBeCloseTo(360, 1);
  });

  it("shoot cooldown starts at 0.3s and scales ×0.88 per fire-rate level with a 0.03 floor", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    step(w, DT, controls({ shoot: true }));
    expect(p.shotCooldownTimer).toBeCloseTo(0.3, 10);
    w.economy.levels.fire_rate = 1;
    // A shot must fully drain before the next fires (18 ticks at 0.3s) —
    // the Python build gates on cooldown > 0 and decrements per frame.
    for (let i = 0; i < 20; i++) step(w, DT, {});
    step(w, DT, controls({ shoot: true }));
    expect(p.shotCooldownTimer).toBeCloseTo(0.264, 10); // 0.3 × 0.88
    w.economy.levels.fire_rate = 40;
    for (let i = 0; i < 20; i++) step(w, DT, {});
    step(w, DT, controls({ shoot: true }));
    expect(p.shotCooldownTimer).toBeCloseTo(0.03, 10); // the floor
  });

  it("fires at most one shot per cooldown window", () => {
    const w = soloWorld(1);
    for (let i = 0; i < 5; i++) step(w, DT, controls({ shoot: true }));
    expect(w.shots).toHaveLength(1); // ticks 1: fired; 2–5: cooling down
  });
});

describe("invulnerability window (game.respawn)", () => {
  it("an invulnerable ship does not lose a life to an overlapping rock", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    placeAsteroid(w, p.x, p.y, 0, 0, 60);
    step(w, DT, {});
    expect(p.lives).toBe(3);
    expect(w.phase).toBe("playing");
  });

  it("after the grace expires, a collision costs a life and respawns centered", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    placeAsteroid(w, p.x, p.y, 0, 0, 60);
    for (let i = 0; i < 130; i++) step(w, DT, {}); // 2.1667s > 2.0s grace
    expect(p.lives).toBe(2);
    expect(p.x).toBe(640); // respawned at center
    expect(p.y).toBe(360);
    expect(p.invulnerabilityTimer).toBeGreaterThan(0); // fresh grace window
  });
});

describe("shield pickup (powerups F4)", () => {
  it("collecting a shield stocks one hit and arms 8s; it absorbs a hit with no life lost", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    w.powerups.push({ id: w.nextEntityId++, x: p.x, y: p.y, vx: 0, vy: 0, kind: "shield" });
    const events = step(w, DT, {});
    expect(events.filter((e) => e.k === "pickup")).toEqual([{ k: "pickup", kind: "shield" }]);
    expect(p.powerupTimers.shield).toBeCloseTo(8.0, 6);
    expect(p.shieldHits).toBe(1);
    // Now a rock lands on the ship (grace zeroed): the shield eats it.
    p.invulnerabilityTimer = 0;
    placeAsteroid(w, p.x, p.y, 0, 0, 60);
    step(w, DT, {});
    expect(p.lives).toBe(3);
    expect(p.shieldHits).toBe(0);
    // Absorption grants no invulnerability: the very next tick hits for real.
    step(w, DT, {});
    expect(p.lives).toBe(2);
  });
});

describe("rapid and triple pickups (powerups F4)", () => {
  it("RAPID cuts the cooldown ×0.4", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    w.powerups.push({ id: w.nextEntityId++, x: p.x, y: p.y, vx: 0, vy: 0, kind: "rapid" });
    step(w, DT, {});
    step(w, DT, controls({ shoot: true }));
    expect(p.shotCooldownTimer).toBeCloseTo(0.12, 10); // 0.3 × 0.4
  });

  it("TRIPLE fires a three-way spread", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    w.powerups.push({ id: w.nextEntityId++, x: p.x, y: p.y, vx: 0, vy: 0, kind: "triple" });
    step(w, DT, {});
    step(w, DT, controls({ shoot: true }));
    expect(w.shots).toHaveLength(3);
    const angles = w.shots.map((s) => (Math.atan2(s.vy, s.vx) * 180) / Math.PI);
    // Ship faces rotation 0 → shots along UP (0,1); atan2(1, 0) is 90°.
    expect(angles.sort((a, b) => a - b)[1]).toBeCloseTo(90, 6);
  });
});

describe("chrono dilation (bought powerup)", () => {
  it("halves asteroid motion the tick after arming and restores it at expiry", () => {
    const w = soloWorld(1);
    w.economy.credits = 300;
    buy(w, 0); // chrono, 8s
    const rock = placeAsteroid(w, 200, 200, 100, 0, 20);
    step(w, DT, {}); // activation tick: still full speed; scale published for the next
    const x1 = rock.x;
    step(w, DT, {});
    expect(rock.x - x1).toBeCloseTo(100 * 0.5 * DT, 6);
    // 10s in: the 8s timer has expired — full speed again.
    for (let i = 0; i < 600 - 2; i++) step(w, DT, {});
    const xEnd = rock.x;
    step(w, DT, {});
    expect(rock.x - xEnd).toBeCloseTo(100 * DT, 6);
  });
});

describe("drones (drones.py)", () => {
  it("fields one turret per level, evenly staggered first shots", () => {
    const w = soloWorld(5);
    w.field.spawnTimer = -1e9; // freeze the field: no spawned rocks here
    w.economy.credits = 100;
    buy(w, 4);
    step(w, DT, {});
    expect(w.drones).toHaveLength(1);
    w.economy.credits = 230; // level-2 cost is 100 × 2.2 — which floats to 220.000…3, so 220 credits are refused exactly as Python refuses them
    buy(w, 4); // level 2
    step(w, DT, {});
    expect(w.drones).toHaveLength(2);
  });

  it("fires on the 1.5s cadence — first shot at 0.75s for a single turret", () => {
    const w = soloWorld(5);
    w.field.spawnTimer = -1e9; // freeze the field: no spawned rocks here
    w.economy.credits = 100;
    buy(w, 4);
    // Track shots by id: culling removes bodies, ids never repeat.
    let maxShotId = 0;
    for (let t = 1; t <= 140; t++) {
      step(w, DT, {});
      for (const s of w.shots) maxShotId = Math.max(maxShotId, s.id);
      if (t < 45) expect(maxShotId, `tick ${t}`).toBe(0);
      if (t >= 45 && t < 135) expect(maxShotId, `tick ${t}`).toBe(1);
    }
    expect(maxShotId).toBe(2); // second shot fired at tick 135 (0.75 + 1.5s)
  });

  it("drone shots pay the shared ledger, never a personal score", () => {
    const w = soloWorld(5);
    w.field.spawnTimer = -1e9; // freeze the field: only the placed rock exists
    w.economy.levels.drone = 1;
    placeAsteroid(w, 640, 100, 0, 0, 20); // small rock well inside the screen
    for (let i = 0; i < 100; i++) step(w, DT, {});
    expect(must(w.players.p1, "p1").score).toBe(0);
    expect(w.economy.credits).toBeCloseTo(100, 6); // 100 for the small rock
    expect(w.asteroids).toHaveLength(0);
  });
});

describe("co-op lives and game over (game.py, pluralized)", () => {
  function twoPlayerWorld(): World {
    const w = newWorld(1);
    addPlayer(w, "A", "Alpha");
    addPlayer(w, "B", "Beta");
    return w;
  }

  function burnLives(w: World, id: string, hits: number): GameEvent[] {
    const p = must(w.players[id], id);
    let events: GameEvent[] = [];
    for (let i = 0; i < hits; i++) {
      p.invulnerabilityTimer = 0;
      placeAsteroid(w, p.x, p.y, 0, 0, 60);
      events = step(w, DT, {});
    }
    return events;
  }

  it("A out while B lives: A spectates, the run continues", () => {
    const w = twoPlayerWorld();
    burnLives(w, "A", 3);
    expect(must(w.players.A, "A").lives).toBe(0);
    expect(must(w.players.B, "B").lives).toBe(3);
    expect(w.phase).toBe("playing");
  });

  it("game over only when every player is out", () => {
    const w = twoPlayerWorld();
    burnLives(w, "A", 3);
    burnLives(w, "B", 3);
    expect(w.phase).toBe("game_over");
  });

  it("the gameOver event fires on the killing step", () => {
    const w = twoPlayerWorld();
    burnLives(w, "A", 3);
    const events = burnLives(w, "B", 3); // B's third hit ends the run
    expect(events.filter((e) => e.k === "gameOver")).toEqual([{ k: "gameOver" }]);
  });
});

describe("restart (game.restart + main's reset block)", () => {
  it("is refused while playing", () => {
    const w = soloWorld();
    expect(requestRestart(w)).toEqual([]);
    expect(w.phase).toBe("playing");
  });

  it("re-seeds the run and keeps the ledger", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    placeAsteroid(w, p.x, p.y, 0, 0, 60);
    for (let i = 0; i < 3; i++) {
      p.invulnerabilityTimer = 0;
      placeAsteroid(w, p.x, p.y, 0, 0, 60);
      step(w, DT, {});
    }
    expect(w.phase).toBe("game_over");
    const creditsBefore = w.economy.credits;
    const events = requestRestart(w);
    expect(events).toEqual([{ k: "waveStarted", wave: 1 }]);
    expect(w.wave).toBe(1);
    expect(w.phase).toBe("playing");
    expect(w.asteroids).toHaveLength(0);
    expect(w.shots).toHaveLength(0);
    expect(p.lives).toBe(3);
    expect(p.x).toBe(640);
    expect(p.y).toBe(360);
    expect(p.powerupTimers).toEqual({});
    expect(w.economy.credits).toBe(creditsBefore); // the ledger persists across runs
  });
});

describe("MAX_DT clamp (constants.MAX_DT)", () => {
  it("caps a single step at 0.1s so stalls never tunnel entities", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    for (let i = 0; i < 6; i++) step(w, 0.5, controls({ thrust: true }));
    // 6 × 0.1s × 200 px/s = 120 px — not 6 × 0.5s × 200 = 600 px.
    expect(p.y).toBeCloseTo(360 + 120, 1);
  });
});

describe("off-screen culls never mint (main.destroyed_asteroids)", () => {
  it("a rock drifting past the bounds disappears silently", () => {
    const w = soloWorld(1);
    placeAsteroid(w, 1400, 360, 1000, 0, 60); // fully beyond the bounds + margin
    const events = step(w, DT, {});
    expect(w.asteroids).toHaveLength(0);
    expect(events.filter((e) => e.k === "mint")).toHaveLength(0);
    expect(w.economy.credits).toBe(0);
  });
});

describe("nuke (bought powerup, main.nuke_field)", () => {
  it("splits the field to completion and mints each on-screen rock exactly once", () => {
    const w = soloWorld(1);
    placeAsteroid(w, 400, 300, 0, 0, 60);
    w.economy.credits = 1000;
    const events = buy(w, 8); // nuke: 1000 credits
    expect(w.economy.credits).toBe(20); // 1000 − 1000 + mint(60) at ×1 income
    expect(w.asteroids).toHaveLength(0); // 60 → 40s → 20s → gone
    const mints = events.filter((e) => e.k === "mint");
    expect(mints).toHaveLength(1);
    expect(mints[0]).toMatchObject({ amount: 20 });
    expect(events.filter((e) => e.k === "burst")).toHaveLength(1); // debris for the parent
    expect(events.filter((e) => e.k === "purchase")).toEqual([{ k: "purchase", what: "nuke" }]);
  });
});
