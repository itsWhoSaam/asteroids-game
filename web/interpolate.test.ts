/**
 * Tests for the snapshot interpolation buffer — the room client's render
 * source. Pins: shortest-arc angles, entity-id matching (spawns appear,
 * kills vanish, scalars ride the newest snapshot), alpha clamping, and the
 * hold-at-newest contract (interpolation only, never extrapolation).
 */
import { describe, expect, it } from "vitest";
import type { Snapshot } from "../shared/protocol";
import { DEFAULT_SNAPSHOT_INTERVAL_MS, LerpBuffer, interpolateSnaps, lerp, lerpAngleDeg } from "./interpolate";

function playerSnap(id: string, x: number, y: number, rotation = 0): Snapshot["players"][number] {
  return {
    id,
    name: `P${id}`,
    x,
    y,
    vx: 0,
    vy: 0,
    rotation,
    lives: 3,
    score: 0,
    invulnTimer: 0,
    shieldHits: 0,
  };
}

function snapWith(overrides: Partial<Snapshot>): Snapshot {
  return {
    wave: 1,
    phase: "playing",
    players: [],
    asteroids: [],
    shots: [],
    powerups: [],
    economy: {
      credits: 0,
      levels: { nanoblade: 0, fire_rate: 0, income: 0, drone: 0 },
      powerupUses: {},
      powerupTimers: {},
    },
    drones: [],
    ...overrides,
  };
}

describe("lerp / lerpAngleDeg", () => {
  it("lerps linearly", () => {
    expect(lerp(10, 20, 0.5)).toBe(15);
    expect(lerp(0, 100, 0.25)).toBe(25);
  });

  it("takes the shortest arc across the 0°/360° seam", () => {
    expect(lerpAngleDeg(350, 10, 0.5)).toBeCloseTo(0); // 20° apart, midpoint 0
    expect(lerpAngleDeg(350, 10, 1)).toBeCloseTo(10);
    expect(lerpAngleDeg(350, 10, 0)).toBeCloseTo(350);
  });

  it("keeps plain small deltas intact", () => {
    expect(lerpAngleDeg(90, 120, 0.5)).toBeCloseTo(105);
  });
});

describe("interpolateSnaps", () => {
  it("lerps matched players by id and rides the newest scalars", () => {
    const before = snapWith({ players: [playerSnap("a", 100, 200, 350)], wave: 2 });
    const after = snapWith({ players: [playerSnap("a", 200, 300, 10)], wave: 3 });
    const out = interpolateSnaps(before, after, 0.5);
    expect(out.players[0]?.x).toBe(150);
    expect(out.players[0]?.y).toBe(250);
    expect(out.players[0]?.rotation).toBeCloseTo(0); // shortest arc through 0
    expect(out.wave).toBe(3); // scalars come from the newest snapshot
  });

  it("uses next values for ids only in next (new spawns)", () => {
    const before = snapWith({ asteroids: [] });
    const after = snapWith({
      asteroids: [{ id: 7, x: 5, y: 6, vx: 1, vy: 2, radius: 20 }],
    });
    const out = interpolateSnaps(before, after, 0.3);
    expect(out.asteroids).toHaveLength(1);
    expect(out.asteroids[0]).toMatchObject({ id: 7, x: 5, y: 6 });
  });

  it("drops ids only in prev (already dead)", () => {
    const before = snapWith({ shots: [{ id: 3, x: 0, y: 0, vx: 1, vy: 1 }] });
    const after = snapWith({ shots: [] });
    expect(interpolateSnaps(before, after, 0.5).shots).toHaveLength(0);
  });

  it("clamps alpha into [0, 1]", () => {
    const before = snapWith({ players: [playerSnap("a", 0, 0)] });
    const after = snapWith({ players: [playerSnap("a", 10, 0)] });
    expect(interpolateSnaps(before, after, -1).players[0]?.x).toBe(0);
    expect(interpolateSnaps(before, after, 2).players[0]?.x).toBe(10);
  });
});

describe("LerpBuffer", () => {
  it("returns null before any snapshot and the raw snap before two", () => {
    const buffer = new LerpBuffer();
    expect(buffer.sample(1000)).toBeNull();
    const snap = snapWith({});
    buffer.push(snap, 1000);
    expect(buffer.sample(1000)).toBe(snap);
  });

  it("walks between the last two snapshots at the delayed render clock", () => {
    const buffer = new LerpBuffer();
    buffer.push(snapWith({ players: [playerSnap("a", 0, 0)] }), 1000);
    buffer.push(snapWith({ players: [playerSnap("a", 100, 0)] }), 1050);
    // Render clock lags one interval: now 1075 → renderAt 1025 → midpoint.
    const out = buffer.sample(1075);
    expect(out?.players[0]?.x).toBeCloseTo(50);
  });

  it("holds at the newest snapshot when it ages past the window", () => {
    const buffer = new LerpBuffer();
    const newest = snapWith({ players: [playerSnap("a", 100, 0)] });
    buffer.push(snapWith({ players: [playerSnap("a", 0, 0)] }), 1000);
    buffer.push(newest, 1050);
    // Far past the window: hold the newest — no extrapolation.
    expect(buffer.sample(5000, DEFAULT_SNAPSHOT_INTERVAL_MS)).toBe(newest);
  });

  it("ignores stale pushes", () => {
    const buffer = new LerpBuffer();
    const first = snapWith({});
    const newest = snapWith({ wave: 9 });
    buffer.push(first, 2000);
    buffer.push(snapWith({ wave: 1 }), 1000); // older than the newest — dropped
    expect(buffer.sample(3000)).toBe(first);
    buffer.push(snapWith({ wave: 2 }), 1500); // also stale
    expect(buffer.sample(3000)).toBe(first);
    buffer.push(newest, 2500); // fresh — shifts the window forward
    expect(buffer.sample(3000, 0)).toBe(newest);
  });

  it("reset clears the buffer", () => {
    const buffer = new LerpBuffer();
    buffer.push(snapWith({}), 1000);
    buffer.push(snapWith({}), 1050);
    buffer.reset();
    expect(buffer.sample(1200)).toBeNull();
  });
});
