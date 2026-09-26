/**
 * Tests for the semi-3D presentation helpers — the pure seams the renderer
 * leans on. Pins: per-id determinism (the multiplayer contract — same rock
 * id, identical shape and spin on every client), the mirrored look bands
 * (silhouette jitter, crater layout, spin rate), palette-key resolution for
 * every mirrored swatch, and the ship's presentation-clock easing. Canvas
 * bakes need a DOM, so they are exercised by the browser dogfood, not here.
 */
import { describe, expect, it } from "vitest";
import {
  ASTEROID_SPIN_MAX_DPS,
  ASTEROID_SPIN_MIN_DPS,
  CANOPY_GLINT_FRACTION,
  CANOPY_RADIUS_X,
  CRATER_RADIUS_FRACTION,
  ENGINE_GLOW_REACH_IDLE_PX,
  ENGINE_GLOW_REACH_THRUST_PX,
  HULL_GRADIENT_BANDS,
  PALETTE,
  PLAYER_RADIUS,
  PLAYER_SPEED,
  PLAYER_TURN_SPEED,
  SILHOUETTE_JITTER,
  SILHOUETTE_LIGHT_ANGLE,
  SILHOUETTE_VERTICES,
} from "../shared/constants";
import type { PlayerSnap } from "../shared/protocol";
import { rotateDeg } from "../shared/sim";
import {
  asteroidShadeColors,
  canopyGlintCenter,
  canopyPoints,
  craterSpecs,
  engineGlowBackingColor,
  engineGlowGeometry,
  hullBandColor,
  hullGradientBands,
  mixColors,
  pruneShipClocks,
  rockInkPoints,
  silhouettePoints,
  silhouetteRadiusAt,
  spinAngleFor,
  spinRateFor,
  thrustTargetFor,
  updateShipClocks,
} from "./sem3d";

describe("silhouettePoints (determinism per id)", () => {
  it("derives identical vertices from the same id", () => {
    expect(silhouettePoints(40, 1234)).toEqual(silhouettePoints(40, 1234));
  });

  it("derives different rocks from different ids", () => {
    expect(silhouettePoints(40, 1)).not.toEqual(silhouettePoints(40, 2));
  });

  it("scales the same id's shape exactly with radius", () => {
    const small = silhouettePoints(20, 777);
    const large = silhouettePoints(60, 777);
    expect(large.length).toBe(small.length);
    large.forEach((v, i) => {
      const s = small[i];
      expect(s).toBeDefined();
      if (!s) return;
      expect(v.x).toBeCloseTo(s.x * 3, 9);
      expect(v.y).toBeCloseTo(s.y * 3, 9);
    });
  });
});

describe("silhouettePoints (the mirrored shape band)", () => {
  it("keeps the vertex count inside the desktop band across many ids", () => {
    for (let id = 1; id <= 60; id += 1) {
      const count = silhouettePoints(40, id).length;
      expect(count).toBeGreaterThanOrEqual(SILHOUETTE_VERTICES[0]);
      expect(count).toBeLessThanOrEqual(SILHOUETTE_VERTICES[1]);
    }
  });

  it("jitters every vertex radius within ±SILHOUETTE_JITTER", () => {
    for (let id = 1; id <= 60; id += 1) {
      for (const v of silhouettePoints(40, id)) {
        const reach = Math.hypot(v.x, v.y);
        expect(reach).toBeGreaterThanOrEqual(40 * (1 - SILHOUETTE_JITTER[1]) - 1e-9);
        expect(reach).toBeLessThanOrEqual(40 * (1 + SILHOUETTE_JITTER[1]) + 1e-9);
      }
    }
  });
});

describe("craterSpecs (the mirrored crater layout)", () => {
  it("lays 2–5 craters inside the hull for every id", () => {
    for (let id = 1; id <= 60; id += 1) {
      const craters = craterSpecs(50, id);
      expect(craters.length).toBeGreaterThanOrEqual(2);
      expect(craters.length).toBeLessThanOrEqual(5);
      for (const c of craters) {
        expect(Math.hypot(c.offset.x, c.offset.y)).toBeLessThanOrEqual(0.62 * 50 + 1e-9);
        expect(c.rx).toBeGreaterThanOrEqual(CRATER_RADIUS_FRACTION[0] * 50 - 1e-9);
        expect(c.rx).toBeLessThanOrEqual(CRATER_RADIUS_FRACTION[1] * 50 + 1e-9);
        expect(c.ry).toBeLessThan(c.rx); // squashed along one axis
      }
    }
  });

  it("is deterministic per id", () => {
    expect(craterSpecs(50, 999)).toEqual(craterSpecs(50, 999));
  });
});

describe("spin (deterministic tumble per id)", () => {
  it("keeps the signed rate inside the desktop band", () => {
    for (let id = 1; id <= 60; id += 1) {
      const rate = Math.abs(spinRateFor(id));
      expect(rate).toBeGreaterThanOrEqual(ASTEROID_SPIN_MIN_DPS - 1e-9);
      expect(rate).toBeLessThanOrEqual(ASTEROID_SPIN_MAX_DPS + 1e-9);
    }
  });

  it("spins both directions across the field", () => {
    const signs = new Set([...Array(60).keys()].map((id) => Math.sign(spinRateFor(id + 1))));
    expect(signs.has(-1)).toBe(true);
    expect(signs.has(1)).toBe(true);
  });

  it("gives the same id the same angle at the same presentation time", () => {
    expect(spinAngleFor(321, 12.34)).toBe(spinAngleFor(321, 12.34));
  });

  it("advances the angle with time and wraps into [0, 360)", () => {
    expect(spinAngleFor(321, 2)).not.toBe(spinAngleFor(321, 1));
    for (let t = 0; t <= 400; t += 7) {
      const angle = spinAngleFor(321, t);
      expect(angle).toBeGreaterThanOrEqual(0);
      expect(angle).toBeLessThan(360);
    }
  });
});

describe("rockInkPoints (the ink stack's lumpy path)", () => {
  it("translates the seeded silhouette to the rock's frame at spin 0", () => {
    const rock = { id: 42, x: 300, y: 200, vx: 0, vy: 0, radius: 40 };
    const base = silhouettePoints(40, 42);
    const inked = rockInkPoints(rock, 0);
    expect(inked.length).toBe(base.length);
    inked.forEach((v, i) => {
      const b = base[i];
      expect(b).toBeDefined();
      if (!b) return;
      expect(v.x).toBeCloseTo(300 + b.x, 9);
      expect(v.y).toBeCloseTo(200 + b.y, 9);
    });
  });

  it("tumbles with the spin: same id and angle → same points", () => {
    const rock = { id: 42, x: 300, y: 200, vx: 0, vy: 0, radius: 40 };
    const spin = spinAngleFor(42, 9.5);
    expect(rockInkPoints(rock, spin)).toEqual(rockInkPoints(rock, spin));
  });
});

describe("silhouetteRadiusAt (the shadow band's rim sampling)", () => {
  it("measures the true ray reach between vertices of a diamond", () => {
    const r = 40;
    const diamond = [
      { x: r, y: 0 },
      { x: 0, y: r },
      { x: -r, y: 0 },
      { x: 0, y: -r },
    ];
    expect(silhouetteRadiusAt(diamond, 0)).toBeCloseTo(r, 9);
    expect(silhouetteRadiusAt(diamond, 45)).toBeCloseTo(r / Math.SQRT2, 9);
  });
});

describe("asteroidShadeColors (palette-key resolution)", () => {
  it("resolves each size tier through its own shadow/highlight keys", () => {
    expect(asteroidShadeColors(20)).toEqual({
      tier: PALETTE.asteroid_s,
      shadow: PALETTE.asteroid_shadow_s,
      highlight: PALETTE.asteroid_highlight_s,
    });
    expect(asteroidShadeColors(40)).toEqual({
      tier: PALETTE.asteroid_m,
      shadow: PALETTE.asteroid_shadow_m,
      highlight: PALETTE.asteroid_highlight_m,
    });
    expect(asteroidShadeColors(60)).toEqual({
      tier: PALETTE.asteroid_l,
      shadow: PALETTE.asteroid_shadow_l,
      highlight: PALETTE.asteroid_highlight_l,
    });
  });

  it("clamps odd radii into the tier band", () => {
    expect(asteroidShadeColors(0).shadow).toEqual(PALETTE.asteroid_shadow_s);
    expect(asteroidShadeColors(1000).shadow).toEqual(PALETTE.asteroid_shadow_l);
  });
});

describe("mirrored palette keys (the desktop-landed values)", () => {
  it("carries the ship swatches exactly", () => {
    expect(PALETTE.ship_hull_shade).toEqual([35, 82, 113]);
    expect(PALETTE.ship_canopy).toEqual([168, 244, 248]);
    expect(PALETTE.ship_drop_shadow).toEqual([13, 10, 32]);
    expect(PALETTE.engine_glow).toEqual([255, 130, 74]);
  });

  it("carries the asteroid shadow swatches exactly", () => {
    expect(PALETTE.asteroid_shadow_l).toEqual([78, 39, 127]);
    expect(PALETTE.asteroid_shadow_m).toEqual([104, 27, 90]);
    expect(PALETTE.asteroid_shadow_s).toEqual([104, 49, 112]);
  });

  it("carries the asteroid highlight swatches exactly", () => {
    expect(PALETTE.asteroid_highlight_l).toEqual([214, 137, 169]);
    expect(PALETTE.asteroid_highlight_m).toEqual([255, 119, 110]);
    expect(PALETTE.asteroid_highlight_s).toEqual([255, 153, 146]);
  });

  it("melts the glow backing toward the paper without alpha", () => {
    expect(engineGlowBackingColor()).toEqual(mixColors(PALETTE.engine_glow, PALETTE.paper, 0.55));
  });
});

describe("mixColors (the no-alpha color fade)", () => {
  it("returns the endpoints and midpoint", () => {
    const a: [number, number, number] = [10, 20, 30];
    const b: [number, number, number] = [50, 60, 70];
    expect(mixColors(a, b, 0)).toEqual(a);
    expect(mixColors(a, b, 1)).toEqual(b);
    expect(mixColors(a, b, 0.5)).toEqual([30, 40, 50]);
  });
});

describe("hullGradientBands (the banded cel hull)", () => {
  const nose = { x: 100, y: 0 };
  const tailA = { x: 0, y: 10 };
  const tailB = { x: 0, y: -10 };

  it("tiles the hull into HULL_GRADIENT_BANDS quads spanning the full gradient", () => {
    const bands = hullGradientBands(nose, tailA, tailB, HULL_GRADIENT_BANDS);
    expect(bands.length).toBe(HULL_GRADIENT_BANDS);
    expect(bands[0]?.fraction).toBe(0);
    expect(bands[bands.length - 1]?.fraction).toBe(1);
  });

  it("walks each band's inner edge from the tail toward the nose", () => {
    const bands = hullGradientBands(nose, tailA, tailB, HULL_GRADIENT_BANDS);
    bands.forEach((band, i) => {
      const t = i / HULL_GRADIENT_BANDS;
      const first = band.quad[0];
      expect(first?.x).toBeCloseTo(tailA.x + (nose.x - tailA.x) * t, 9);
      expect(first?.y).toBeCloseTo(tailA.y + (nose.y - tailA.y) * t, 9);
    });
  });

  it("resolves band colors through the palette: pure shade at the tail, hull at the nose", () => {
    const hull = PALETTE.ship;
    expect(hullBandColor(hull, 0)).toEqual(PALETTE.ship_hull_shade);
    expect(hullBandColor(hull, 1)).toEqual(hull);
  });
});

describe("canopy (the hull dome and its glint)", () => {
  const nose = { x: 100, y: 0 };
  const tailA = { x: 0, y: 10 };
  const tailB = { x: 0, y: -10 };

  it("sits the dome on the hull centroid at the canopy radius", () => {
    const dome = canopyPoints(nose, tailA, tailB, 0);
    expect(dome.length).toBe(12);
    const cx = (nose.x + tailA.x + tailB.x) / 3;
    const cy = (nose.y + tailA.y + tailB.y) / 3;
    const meanX = dome.reduce((sum, p) => sum + p.x, 0) / dome.length;
    const meanY = dome.reduce((sum, p) => sum + p.y, 0) / dome.length;
    expect(meanX).toBeCloseTo(cx, 9);
    expect(meanY).toBeCloseTo(cy, 9);
    const reach = Math.max(...dome.map((p) => Math.hypot(p.x - cx, p.y - cy)));
    expect(reach).toBeCloseTo(PLAYER_RADIUS * CANOPY_RADIUS_X, 9);
  });

  it("throws the glint toward the shared light (up-left at rest)", () => {
    const glint = canopyGlintCenter(nose, tailA, tailB);
    const cx = (nose.x + tailA.x + tailB.x) / 3;
    const cy = (nose.y + tailA.y + tailB.y) / 3;
    expect(glint.x).toBeLessThan(cx); // light leans left
    expect(glint.y).toBeLessThan(cy); // and up (the y-down frame)
    const light = rotateDeg({ x: 1, y: 0 }, SILHOUETTE_LIGHT_ANGLE);
    expect(glint.x).toBeCloseTo(cx + light.x * PLAYER_RADIUS * CANOPY_GLINT_FRACTION, 9);
    expect(glint.y).toBeCloseTo(cy + light.y * PLAYER_RADIUS * CANOPY_GLINT_FRACTION, 9);
  });
});

describe("engineGlowGeometry (the throttle plume)", () => {
  it("reaches the mirrored idle and thrust distances, wider under throttle", () => {
    const idle = engineGlowGeometry(500, 300, 0, 0);
    const full = engineGlowGeometry(500, 300, 0, 1);
    const idleReach = Math.hypot(idle.apex.x - 500, idle.apex.y - 300);
    const fullReach = Math.hypot(full.apex.x - 500, full.apex.y - 300);
    expect(idleReach).toBeCloseTo(ENGINE_GLOW_REACH_IDLE_PX, 9);
    expect(fullReach).toBeCloseTo(ENGINE_GLOW_REACH_THRUST_PX, 9);
    expect(full.halfWidth).toBeGreaterThan(idle.halfWidth);
  });

  it("keeps the plume inside the halo tripwire's 25px band at any throttle", () => {
    for (const thrust of [0, 0.5, 1]) {
      const glow = engineGlowGeometry(500, 300, 0, thrust);
      const reach = Math.hypot(glow.apex.x - 500, glow.apex.y - 300);
      expect(reach).toBeLessThan(25); // the halo band's inner edge
    }
  });
});

describe("thrustTargetFor (the snapshot-derived throttle)", () => {
  it("reads full throttle from velocity along the nose", () => {
    // Rotation 0 faces (0, 1): thrusting straight down is +vy.
    const p = { ...playerSnap("p1"), vy: PLAYER_SPEED };
    expect(thrustTargetFor(p)).toBe(1);
  });

  it("reads rest as the idle ember and clamps reverse thrust to zero", () => {
    expect(thrustTargetFor(playerSnap("p1"))).toBe(0);
    const reversing = { ...playerSnap("p1"), vy: -PLAYER_SPEED };
    expect(thrustTargetFor(reversing)).toBe(0);
  });
});

describe("updateShipClocks (bank and throttle easing)", () => {
  it("eases the bank toward a sustained full-rate turn and back to level", () => {
    const id = "bank-test";
    let now = 0;
    const warmup = updateShipClocks(playerSnap(id), now); // first call: no history
    expect(warmup.bank).toBe(0);
    let snap = { ...playerSnap(id), rotation: 0 };
    // A full-rate clockwise turn (the sim's PLAYER_TURN_SPEED per second).
    for (let frame = 0; frame < 30; frame += 1) {
      now += 1 / 60;
      snap = { ...snap, rotation: PLAYER_TURN_SPEED * now };
      const { bank } = updateShipClocks(snap, now);
      expect(bank).toBeGreaterThan(0);
      expect(bank).toBeLessThanOrEqual(1);
    }
    // Cut the turn: the bank eases back toward level without flipping sign.
    for (let frame = 0; frame < 60; frame += 1) {
      now += 1 / 60;
      const { bank } = updateShipClocks(snap, now);
      expect(bank).toBeGreaterThanOrEqual(0);
      if (frame === 59) expect(bank).toBeCloseTo(0, 1);
    }
  });

  it("eases the throttle up under sustained thrust", () => {
    const id = "thrust-test";
    let now = 0;
    const thrusting = { ...playerSnap(id), vy: PLAYER_SPEED };
    expect(updateShipClocks(thrusting, now).thrust).toBe(0); // no history yet
    let thrust = 0;
    for (let frame = 0; frame < 30; frame += 1) {
      now += 1 / 60;
      thrust = updateShipClocks(thrusting, now).thrust;
      expect(thrust).toBeGreaterThan(0);
      expect(thrust).toBeLessThanOrEqual(1);
    }
    expect(thrust).toBeGreaterThan(0.5); // well up the response curve by now
  });

  it("holds stale clocks across a long frame gap (respawn, tab stall)", () => {
    const id = "gap-test";
    let now = 0;
    for (let frame = 0; frame < 10; frame += 1) {
      now += 1 / 60;
      updateShipClocks({ ...playerSnap(id), rotation: PLAYER_TURN_SPEED * now }, now);
    }
    // A ship reappearing after a 2s gap must not read as a phantom
    // 2-second turn: the clock holds its bank instead of easing.
    const before = updateShipClocks({ ...playerSnap(id), rotation: 180 }, now);
    now += 2;
    const after = updateShipClocks({ ...playerSnap(id), rotation: 180 }, now);
    expect(after.bank).toBe(before.bank);
  });

  it("prunes clocks for players that left the snapshot", () => {
    const id = "prune-test";
    let now = 0;
    for (let frame = 0; frame < 5; frame += 1) {
      now += 1 / 60;
      updateShipClocks(playerSnap(id), now);
    }
    pruneShipClocks(["someone-else"]);
    // A pruned ship starts from a fresh clock: no stale bank eases in.
    const { bank } = updateShipClocks(playerSnap(id), now);
    expect(bank).toBe(0);
  });
});

function playerSnap(id: string): PlayerSnap {
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
  };
}
