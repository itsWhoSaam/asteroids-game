/**
 * Tests for the renderer's pure geometry and color seams — the canvas draw
 * calls themselves are exercised by the browser dogfood, not unit tests.
 * Pins: the desktop ship triangle shape, tier colors, and per-seat hull
 * color assignment.
 */
import { describe, expect, it } from "vitest";
import { BANK_FRACTION, PALETTE, PLAYER_RADIUS } from "../shared/constants";
import type { PlayerSnap } from "../shared/protocol";
import { asteroidColor, assignShipColors, shipTriangle } from "./render";

describe("shipTriangle (player.py triangle)", () => {
  it("puts the tip on the nose and the base behind", () => {
    const points = shipTriangle(100, 200, 0);
    const [tip, baseLeft, baseRight] = points;
    // Rotation 0 faces (0, 1) — screen-down — per the shared rotateDeg;
    // rotateDeg((0,1), 90) = (-1, 0) puts the base's offset on +x.
    expect(tip).toEqual({ x: 100, y: 200 + PLAYER_RADIUS });
    expect(baseLeft?.x).toBeCloseTo(100 + PLAYER_RADIUS / 1.5);
    expect(baseLeft?.y).toBeCloseTo(200 - PLAYER_RADIUS);
    expect(baseRight?.x).toBeCloseTo(100 - PLAYER_RADIUS / 1.5);
    expect(baseRight?.y).toBeCloseTo(200 - PLAYER_RADIUS);
  });

  it("turns the tip with rotation (90° points along -x in sim coords)", () => {
    const [tip] = shipTriangle(0, 0, 90);
    // rotateDeg((0,1), 90) = (-1, 0): the tip is at x - radius.
    expect(tip?.x).toBeCloseTo(-PLAYER_RADIUS);
    expect(tip?.y).toBeCloseTo(0);
  });

  it("banks the wing offsets about the tail center without moving the tip", () => {
    const level = shipTriangle(0, 0, 0);
    const banked = shipTriangle(0, 0, 0, 1); // full lean
    expect(banked[0]).toEqual(level[0]); // the nose never moves
    // The wings' offsets FROM THE TAIL CENTER scale by (1 ∓ BANK_FRACTION).
    // At rotation 0 the offset runs purely along x (right = (-1, 0)); the
    // base vertices share the tail center's y, which never scales.
    const tailCenterY = -PLAYER_RADIUS;
    expect(banked[2]?.x).toBeCloseTo((level[2]?.x ?? 0) * (1 + BANK_FRACTION), 9);
    expect(banked[2]?.y).toBe(tailCenterY);
    expect(banked[1]?.x).toBeCloseTo((level[1]?.x ?? 0) * (1 - BANK_FRACTION), 9);
    expect(banked[1]?.y).toBe(tailCenterY);
  });

  it("stays exactly the pinned plan at the default bank", () => {
    // The historical pins above run bank=0 — this pins that default
    // explicitly, so the look change can never move the plain triangle.
    expect(shipTriangle(50, 60, 30)).toEqual(shipTriangle(50, 60, 30, 0));
  });
});

describe("asteroidColor (asteroid.asteroid_color)", () => {
  it("maps size tiers to their palette hues", () => {
    expect(asteroidColor(20)).toEqual(PALETTE.asteroid_s); // small pink
    expect(asteroidColor(40)).toEqual(PALETTE.asteroid_m); // medium magenta
    expect(asteroidColor(60)).toEqual(PALETTE.asteroid_l); // large violet
  });

  it("clamps odd radii into the tier band", () => {
    expect(asteroidColor(0)).toEqual(PALETTE.asteroid_s);
    expect(asteroidColor(1000)).toEqual(PALETTE.asteroid_l);
  });
});

describe("assignShipColors", () => {
  it("assigns one distinct hue per seat, stable across orders", () => {
    const a = playerSnap("p1");
    const b = playerSnap("p2");
    const colorsA = assignShipColors([a, b]);
    const colorsB = assignShipColors([b, a]);
    expect(colorsA.p1).toEqual(PALETTE.ship);
    expect(colorsA.p2).not.toEqual(colorsA.p1);
    expect(colorsB.p1).toEqual(colorsA.p1); // sorted by id, not arrival order
    expect(colorsB.p2).toEqual(colorsA.p2);
  });

  it("cycles after four players", () => {
    const players = ["1", "2", "3", "4", "5"].map((id) => ({ ...playerSnap(id), id }));
    const colors = assignShipColors(players);
    expect(colors["5"]).toEqual(PALETTE.ship); // wraps to seat 0's hue
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
