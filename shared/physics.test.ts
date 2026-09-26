/**
 * Physics mirror suite (physics overhaul): the TypeScript sim asserting the
 * same contracts the Python suite does — momentum conservation in rock
 * bounces, coast-after-release, the speed cap's anti-tunnel arithmetic,
 * ship-only wrap, no-mint bounces, respawn zero-velocity, zero-dt no-ops,
 * and chrono composition — plus the constants parity test, which reads the
 * PYTHON literals from constants.py and fails the moment either file
 * drifts. The two sims share one model; this file is where that stays true.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  COLLISION_RESTITUTION,
  DASH_IMPULSE,
  MAX_DT,
  PLAYER_LINEAR_DAMPING,
  PLAYER_MASS,
  PLAYER_MAX_SPEED,
  PLAYER_RETRO_FACTOR,
  PLAYER_THRUST_ACCEL,
} from "./constants";
import {
  addPlayer,
  asteroidInverseMass,
  newWorld,
  resolveContact,
  step,
} from "./sim";
import type { AsteroidState, ImpulseBody, World } from "./sim";
import type { Controls } from "./protocol";

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

function controls(partial: Partial<Controls>): Record<string, Controls> {
  return { p1: { ...NO_CONTROLS, ...partial } };
}

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

/** A contact-math body at a position with a velocity. */
function body(x: number, y: number, vx: number, vy: number, radius: number): ImpulseBody {
  return { x, y, vx, vy, radius };
}

/** Total momentum of a pair, in mass units (mass = 1 / inverse mass). */
function pairMomentum(a: ImpulseBody, b: ImpulseBody, aInverseMass: number, bInverseMass: number): { x: number; y: number } {
  return {
    x: a.vx / aInverseMass + b.vx / bInverseMass,
    y: a.vy / aInverseMass + b.vy / bInverseMass,
  };
}

// ---------------------------------------------------------------------------
// resolveContact — the pure circleshape.resolveContact mirror
// ---------------------------------------------------------------------------

describe("resolveContact (circleshape.resolveContact mirror)", () => {
  it("equal-mass head-on contacts exchange velocities scaled by restitution", () => {
    const a = body(0, 0, 100, 0, 20);
    const b = body(30, 0, -100, 0, 20); // 10 px overlap, approaching
    const j = resolveContact(a, b, 1, 1);
    expect(j).not.toBeNull();
    // e = 0.85: each leaves at 85 px/s — a perfect exchange, scaled.
    expect(a.vx).toBeCloseTo(-85, 6);
    expect(b.vx).toBeCloseTo(85, 6);
  });

  it("conserves momentum exactly along the normal (vector sum invariant)", () => {
    const a = body(0, 0, 100, 30, 20);
    const b = body(30, 0, -100, -10, 20);
    const before = pairMomentum(a, b, 1, 1);
    resolveContact(a, b, 1, 1);
    const after = pairMomentum(a, b, 1, 1);
    expect(after.x).toBeCloseTo(before.x, 6);
    expect(after.y).toBeCloseTo(before.y, 6);
  });

  it("dissipates the (1 − e²) share of the pair's kinetic energy", () => {
    const a = body(0, 0, 100, 0, 20);
    const b = body(30, 0, -100, 0, 20);
    const ke = (v: ImpulseBody): number => 0.5 * (v.vx ** 2 + v.vy ** 2); // unit masses
    const before = ke(a) + ke(b);
    resolveContact(a, b, 1, 1);
    const after = ke(a) + ke(b);
    expect(after / before).toBeCloseTo(COLLISION_RESTITUTION ** 2, 6);
    expect(after).toBeLessThan(before); // the bounce is real but not elastic
  });

  it("unequal masses shift the light rock more — momentum still invariant", () => {
    // A small rock (r 20, mass 1) meets a large one (r 60, mass 9).
    const a = body(0, 0, 90, 0, 20);
    const b = body(70, 0, -30, 0, 60);
    const aInv = asteroidInverseMass(20);
    const bInv = asteroidInverseMass(60);
    const before = pairMomentum(a, b, aInv, bInv);
    resolveContact(a, b, aInv, bInv);
    const after = pairMomentum(a, b, aInv, bInv);
    expect(after.x).toBeCloseTo(before.x, 6);
    expect(after.y).toBeCloseTo(before.y, 6);
    // The light rock's velocity change dwarfs the heavy one's.
    expect(Math.abs(a.vx - 90)).toBeGreaterThan(Math.abs(b.vx + 30) * 5);
  });

  it("de-penetrates the full overlap, split by inverse mass", () => {
    const a = body(0, 0, 0, 0, 20); // light: inverse mass 1
    const b = body(10, 0, 0, 0, 20); // 30 px overlap
    resolveContact(a, b, 1, asteroidInverseMass(60)); // heavy partner: 1/9
    // The light body gives way: 9/10 of the separation, the heavy 1/10 —
    // and the pair ends exactly touching, never interpenetrating.
    const dist = Math.hypot(b.x - a.x, b.y - a.y);
    expect(dist).toBeCloseTo(40, 6);
    expect(a.x).toBeLessThan(0);
    expect(b.x).toBeGreaterThan(10);
  });

  it("separating contacts only de-penetrate — no impulse adds speed", () => {
    const a = body(0, 0, -100, 0, 20); // flying apart already
    const b = body(30, 0, 100, 0, 20);
    const j = resolveContact(a, b, 1, 1);
    expect(j).toBe(0); // de-penetration only
    expect(a.vx).toBe(-100);
    expect(b.vx).toBe(100);
    expect(b.x - a.x).toBeGreaterThanOrEqual(40); // overlap resolved
  });

  it("an immovable body (inverse mass 0 — the Boss's wall contract) never moves", () => {
    const a = body(0, 0, 100, 0, 20);
    const wall = body(30, 0, 0, 0, 60);
    const wallStart = { x: wall.x, y: wall.y };
    const j = resolveContact(a, wall, 1, 0);
    expect(j).not.toBeNull();
    expect(wall.x).toBe(wallStart.x);
    expect(wall.y).toBe(wallStart.y);
    expect(wall.vx).toBe(0);
    expect(wall.vy).toBe(0);
    // The ship reflects off the wall at e × its closing speed.
    expect(a.vx).toBeCloseTo(-85, 6);
  });

  it("two immovable bodies respond with null and change nothing", () => {
    const a = body(0, 0, 100, 0, 20);
    const b = body(30, 0, -100, 0, 20);
    expect(resolveContact(a, b, 0, 0)).toBeNull();
    expect(a).toEqual(body(0, 0, 100, 0, 20));
    expect(b).toEqual(body(30, 0, -100, 0, 20));
  });

  it("bodies that are not touching return null and change nothing", () => {
    const a = body(0, 0, 100, 0, 20);
    const b = body(100, 0, -100, 0, 20); // 80 px apart, radii sum 40
    expect(resolveContact(a, b, 1, 1)).toBeNull();
    expect(a.vx).toBe(100);
    expect(b.vx).toBe(-100);
  });

  it("chrono composes: a speed-scaled rock exchanges momentum at its dilated speed", () => {
    // Effective velocity = face velocity × 0.5 (chrono): the closing speed
    // into the contact is halved, so the bounce is weaker, not floatier.
    const a = body(0, 0, 100, 0, 20);
    const b = body(30, 0, 0, 0, 20);
    resolveContact(a, b, 1, 1, 0.5, 0.5);
    // closing = (0 − 100) × 0.5 = −50 → j = 1.85 × 50 / 2 = 46.25
    expect(a.vx).toBeCloseTo(100 - 46.25, 6);
    expect(b.vx).toBeCloseTo(46.25, 6);
    // Face momentum is still conserved (the scale cancels in the exchange).
    expect(a.vx + b.vx).toBeCloseTo(100, 6);
  });
});

// ---------------------------------------------------------------------------
// Newtonian ship thrust — the player.py mirror
// ---------------------------------------------------------------------------

describe("Newtonian ship thrust (player.py mirror)", () => {
  it("coasts after release: velocity persists and decays monotonically under damping", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    w.field.spawnTimer = -1e9; // freeze the field: no rocks in this test
    for (let i = 0; i < 30; i++) step(w, DT, controls({ thrust: true }));
    const speedAtRelease = Math.hypot(p.vx, p.vy);
    expect(speedAtRelease).toBeGreaterThan(0);
    let prev = speedAtRelease;
    for (let i = 0; i < 120; i++) {
      // No inputs this whole stretch — the ship coasts.
      step(w, DT, {});
      const speed = Math.hypot(p.vx, p.vy);
      expect(speed).toBeLessThan(prev); // monotonically shrinking…
      expect(speed).toBeGreaterThan(0); // …but never stops dead
      expect(p.vy).toBeGreaterThan(0); // direction holds along the nose
      prev = speed;
    }
    // Exponential drag: e^(−0.5·2) of the release speed after 2 s coasting.
    expect(prev).toBeCloseTo(speedAtRelease * Math.exp(-PLAYER_LINEAR_DAMPING * 2), 3);
  });

  it("retro thrust (S) fires opposite the nose at PLAYER_RETRO_FACTOR of full thrust", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    step(w, DT, controls({ back: true }));
    // Nose (0,1) at rotation 0; retro accelerates along (0,−1) × 0.6.
    expect(p.vy).toBeCloseTo(-PLAYER_THRUST_ACCEL * PLAYER_RETRO_FACTOR * DT * Math.exp(-PLAYER_LINEAR_DAMPING * DT), 6);
    expect(p.vx).toBeCloseTo(0, 9);
  });

  it("caps speed at PLAYER_MAX_SPEED — the anti-tunnel arithmetic holds", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    for (let i = 0; i < 300; i++) step(w, DT, controls({ thrust: true }));
    expect(Math.hypot(p.vx, p.vy)).toBeCloseTo(PLAYER_MAX_SPEED, 6);
    // The cap is the anti-tunnel guarantee: 360 px/s × MAX_DT = 36 px per
    // worst-case frame, inside the 40 px minimum contact overlap.
    expect(PLAYER_MAX_SPEED * MAX_DT).toBeLessThan(40);
  });

  it("wraps the ship across the screen edge with the hull-radius margin", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    w.field.spawnTimer = -1e9; // freeze the field: the wrap must be the only boundary event
    let sawEdge = false;
    for (let i = 0; i < 240; i++) {
      step(w, DT, controls({ thrust: true }));
      if (p.y > 720) sawEdge = true;
      // The ship is never outside the screen by more than its hull margin.
      expect(p.y).toBeGreaterThanOrEqual(-p.radius - 1e-9);
      expect(p.y).toBeLessThanOrEqual(720 + p.radius + 1e-9);
    }
    expect(sawEdge).toBe(true); // it left through the bottom edge…
    // …and re-entered from the top: y is back below the exit point.
    expect(p.y).toBeLessThan(400);
  });

  it("zero-dt frames integrate nothing (frozen-frame no-op)", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    // Two rocks overlapping EACH OTHER, well clear of the ship: a frozen
    // frame must not thrust, damp, shoot, move, de-penetrate, or impulse —
    // the integrators no-op at dt = 0 (the rules hooks still run, as in
    // Python, but nothing here is in rule reach).
    const a = placeAsteroid(w, 200, 300, 50, 0, 60);
    const b = placeAsteroid(w, 240, 300, -50, 0, 60);
    const before = { x: p.x, y: p.y, vx: p.vx, vy: p.vy, invuln: p.invulnerabilityTimer };
    const aBefore = { x: a.x, y: a.y, vx: a.vx, vy: a.vy };
    const events = step(w, 0, controls({ thrust: true, shoot: true }));
    expect(events).toEqual([]);
    expect(p.x).toBe(before.x);
    expect(p.y).toBe(before.y);
    expect(p.vx).toBe(before.vx);
    expect(p.vy).toBe(before.vy);
    expect(p.invulnerabilityTimer).toBe(before.invuln); // timers untouched
    expect(w.shots).toHaveLength(0); // no trigger pull either
    expect(a.x).toBe(aBefore.x);
    expect(a.y).toBe(aBefore.y);
    expect(a.vx).toBe(aBefore.vx); // no movement, no pair resolution
    expect(b.x).toBe(240);
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeLessThan(120); // still overlapping
  });
});

// ---------------------------------------------------------------------------
// The pair pass and the ship impulse, through the real step() loop
// ---------------------------------------------------------------------------

describe("rock pair pass through step() (main.handle_collisions mirror)", () => {
  it("bounces two overlapping rocks — no kill, no mint, no events", () => {
    const w = soloWorld(1);
    placeAsteroid(w, 200, 300, 50, 0, 60);
    placeAsteroid(w, 240, 300, -50, 0, 60); // 80 px overlap, head-on
    const events = step(w, DT, {});
    expect(w.asteroids).toHaveLength(2); // both rocks alive
    expect(w.economy.credits).toBe(0); // nothing minted
    expect(events).toEqual([]); // no explosion, no split, no mint events
    const [a, b] = w.asteroids as [AsteroidState, AsteroidState];
    // Equal area-mass head-on: the bounce exchanges velocities, e-scaled.
    expect(a.vx).toBeCloseTo(-42.5, 6); // 0.85 × 50, reversed
    expect(b.vx).toBeCloseTo(42.5, 6);
    // De-penetrated to touching, not interpenetrating.
    expect(Math.hypot(b.x - a.x, b.y - a.y)).toBeGreaterThanOrEqual(120 - 1e-6);
  });

  it("a many-rock pile stays finite and settles without jitter (stress)", () => {
    const w = soloWorld(1);
    w.field.spawnTimer = -1e9; // freeze the field: only the staged pile exists
    // A tight cluster of eight overlapping rocks, all at rest.
    const cluster: Array<[number, number]> = [
      [200, 300], [230, 300], [215, 326], [185, 326],
      [200, 274], [230, 326], [185, 300], [215, 274],
    ];
    for (const [x, y] of cluster) placeAsteroid(w, x, y, 0, 0, 20);
    for (let i = 0; i < 120; i++) {
      step(w, DT, {});
      for (const a of w.asteroids) {
        expect(Number.isFinite(a.x)).toBe(true);
        expect(Number.isFinite(a.y)).toBe(true);
        expect(Number.isFinite(a.vx)).toBe(true);
        expect(Number.isFinite(a.vy)).toBe(true);
      }
    }
    expect(w.asteroids).toHaveLength(8); // nothing was killed
    expect(w.economy.credits).toBe(0); // and nothing minted
    // Settled: no pair still overlaps.
    for (let i = 0; i < w.asteroids.length; i++) {
      for (let k = i + 1; k < w.asteroids.length; k++) {
        const a = w.asteroids[i]!;
        const b = w.asteroids[k]!;
        expect(Math.hypot(b.x - a.x, b.y - a.y)).toBeGreaterThanOrEqual(a.radius + b.radius - 0.01);
      }
    }
  });

  it("chrono composes through the pair pass: slowed rocks bounce at their dilated speed", () => {
    const w = soloWorld(1);
    w.economy.powerupTimers.chrono = 5; // chrono live from the next publish
    const a = placeAsteroid(w, 200, 300, 100, 0, 20);
    const b = placeAsteroid(w, 400, 300, 0, 0, 20); // apart: the warmup can't touch them
    step(w, DT, {}); // the scale publishes at tick's end for the NEXT tick, Python's order
    expect(w.speedScale).toBe(0.5);
    a.x = 220; // re-stage the 10 px overlap for the measured tick
    b.x = 230;
    const events = step(w, DT, {});
    expect(events).toEqual([]);
    // Dilated closing speed 100 × 0.5 = 50 → j = 1.85 × 50 / 2 = 46.25 —
    // a weaker, heavier-feeling exchange than the 92.5 an unscaled pair gets.
    expect(a.vx).toBeCloseTo(100 - 46.25, 6);
    expect(b.vx).toBeCloseTo(46.25, 6);
  });

  it("a hit shoves both bodies before the rules: the rock keeps its impulse, the respawn zeroes the ship", () => {
    const w = soloWorld(1);
    const p = must(w.players.p1, "p1");
    p.invulnerabilityTimer = 0;
    const rock = placeAsteroid(w, p.x + 30, p.y, -100, 0, 60); // approaching head-on
    const events = step(w, DT, {});
    // The rules ran exactly once.
    expect(events.filter((e) => e.k === "playerHit")).toHaveLength(1);
    expect(p.lives).toBe(2);
    // Respawn contract: centered, zero velocity, fresh grace window.
    expect(p.x).toBe(640);
    expect(p.y).toBe(360);
    expect(p.vx).toBe(0);
    expect(p.vy).toBe(0);
    expect(p.invulnerabilityTimer).toBeGreaterThan(0);
    // The rock kept the shove: the impulse slowed its approach (the ship
    // stole momentum) — physics happened before the rules took the ship.
    expect(rock.vx).toBeGreaterThan(-100);
    expect(rock.vx).toBeLessThan(0);
    expect(w.asteroids).toHaveLength(1); // the hit never kills the rock
  });
});

// ---------------------------------------------------------------------------
// Constants parity — shared/constants.ts == constants.py
// ---------------------------------------------------------------------------

/** Parse the Python literals out of constants.py. LAST assignment wins —
 * the file rebinds names by append (DASH_IMPULSE's 420 → 340 retune), and
 * Python import semantics take the final binding. */
function pythonPhysicsConstants(): Record<string, number> {
  const pyPath = fileURLToPath(new URL("../constants.py", import.meta.url));
  const source = readFileSync(pyPath, "utf8");
  const out: Record<string, number> = {};
  for (const m of source.matchAll(/^\s*([A-Z][A-Z0-9_]*)\s*=\s*(-?[0-9]+(?:\.[0-9]+)?)\s*(?:#.*)?$/gm)) {
    out[m[1]!] = Number(m[2]);
  }
  return out;
}

describe("constants parity (shared/constants.ts == constants.py)", () => {
  it("physics values are identical in both sims", () => {
    const py = pythonPhysicsConstants();
    const pairs: Array<[number, string]> = [
      [PLAYER_THRUST_ACCEL, "PLAYER_THRUST_ACCEL"],
      [PLAYER_RETRO_FACTOR, "PLAYER_RETRO_FACTOR"],
      [PLAYER_MAX_SPEED, "PLAYER_MAX_SPEED"],
      [PLAYER_LINEAR_DAMPING, "PLAYER_LINEAR_DAMPING"],
      [DASH_IMPULSE, "DASH_IMPULSE"],
      [COLLISION_RESTITUTION, "COLLISION_RESTITUTION"],
      [PLAYER_MASS, "PLAYER_MASS"],
    ];
    for (const [tsValue, name] of pairs) {
      const pyValue = py[name];
      expect(pyValue, `${name} must exist in constants.py`).toBeDefined();
      expect(tsValue, `${name} drifted from constants.py`).toBe(pyValue);
    }
  });
});
