/**
 * Tests for the room client's pure seams: the wave-change trigger, the
 * connection-status lines, and ship-color assignment. The loop itself
 * is exercised by dogfooding; these pin its decisions.
 */
import { describe, expect, it } from "vitest";
import { statusText, waveChanged } from "./room";
import { assignShipColors } from "./render";
import type { PlayerSnap, Snapshot } from "../shared/protocol";

function snapWith(wave: number, players: Array<Partial<PlayerSnap>>): Snapshot {
  return {
    tick: 1,
    ack: 0,
    wave,
    phase: "playing",
    players: players.map((p, i) => ({
      id: `p${i}`,
      name: `Pilot ${i}`,
      x: 0,
      y: 0,
      rotation: 0,
      score: 0,
      lives: 3,
      thrusting: false,
      invulnerabilityTimer: 0,
      shieldTimer: 0,
      rapidTimer: 0,
      tripleTimer: 0,
      ...p,
    })),
    asteroids: [],
    shots: [],
    powerups: [],
    events: [],
    economy: {
      credits: 0,
      levels: {},
      powerupUses: {},
      droneCount: 0,
    },
  } as unknown as Snapshot;
}

describe("waveChanged", () => {
  it("fires for the first snapshot and on any wave change", () => {
    const first = snapWith(1, []);
    expect(waveChanged(null, first)).toBe(true);
    expect(waveChanged(first, snapWith(1, []))).toBe(false);
    expect(waveChanged(first, snapWith(2, []))).toBe(true);
  });
});

describe("statusText", () => {
  it("names the 10-second seat hold on reconnect", () => {
    expect(statusText("reconnecting")).toContain("10 seconds");
  });

  it("gives dropped players a plain exit message", () => {
    expect(statusText("dropped")).toContain("The room continues without you");
  });

  it("distinguishes the two rejection reasons", () => {
    expect(statusText("rejected", "room-full")).toContain("full");
    expect(statusText("rejected", "bad-code")).toContain("code");
  });
});

describe("assignShipColors", () => {
  it("assigns distinct colors per player, stable by id", () => {
    const players = snapWith(1, [{ id: "a" }, { id: "b" }, { id: "c" }]).players;
    const colors = assignShipColors(players);
    const set = new Set(Object.values(colors));
    expect(set.size).toBe(3);
    expect(assignShipColors(players)).toEqual(colors);
  });
});
