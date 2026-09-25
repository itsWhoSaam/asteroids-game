/**
 * Tests for the room WebSocket client's reconnect state machine, run
 * against a fake socket and an injected clock (no network, no wall time).
 * Pins the spec's flow: join on open, welcome → connected, seq-monotonic
 * input, rejected is terminal, drop under 10 s retries, over 10 s drops
 * with a plain state, and a healthy welcome resets the retry window.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Snapshot } from "../shared/protocol";
import type { ConnectionStatus, SnapshotMsg, SocketLike } from "./ws";
import { RoomConnection } from "./ws";

class FakeSocket implements SocketLike {
  open = false;
  closed = false;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((data: unknown) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  isOpen(): boolean {
    return this.open;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
  }

  openUp(): void {
    this.open = true;
    this.onopen?.();
  }

  serverMessage(message: unknown): void {
    this.onmessage?.(JSON.stringify(message));
  }

  rawMessage(data: string): void {
    this.onmessage?.(data);
  }

  drop(): void {
    this.open = false;
    this.onclose?.();
  }
}

function snapshotOf(players: Snapshot["players"] = []): Snapshot {
  return {
    wave: 1,
    phase: "playing",
    players,
    asteroids: [],
    shots: [],
    powerups: [],
    economy: { credits: 0, levels: { nanoblade: 0, fire_rate: 0, income: 0, drone: 0 }, powerupUses: {}, powerupTimers: {} },
    drones: [],
  };
}

function harness() {
  const sockets: FakeSocket[] = [];
  const statuses: Array<{ status: ConnectionStatus; reason?: "room-full" | "bad-code" }> = [];
  const welcomes: string[] = [];
  const snapshots: SnapshotMsg[] = [];
  let nowMs = 0;
  const connection = new RoomConnection(
    {
      url: "wss://test/ws",
      room: "ABCD",
      name: "Husam",
      now: () => nowMs,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    },
    {
      onWelcome: (you) => welcomes.push(you),
      onSnapshot: (message) => snapshots.push(message),
      onStatus: (status, reason) => statuses.push({ status, reason }),
    },
  );
  return {
    connection,
    sockets,
    statuses,
    welcomes,
    snapshots,
    tickClock: (ms: number): void => {
      nowMs += ms;
    },
    latest: (): FakeSocket => sockets[sockets.length - 1] as FakeSocket,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("join and welcome", () => {
  it("sends join with the room and name on socket open", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    const sent = h.latest().sent.map((raw) => JSON.parse(raw) as { t: string; room: string; name: string });
    expect(sent).toEqual([{ t: "join", room: "ABCD", name: "Husam" }]);
  });

  it("reports connected and delivers the welcome payload", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.latest().serverMessage({ t: "welcome", you: "p1", tickHz: 60, snapshot: snapshotOf() });
    expect(h.connection.status).toBe("connected");
    expect(h.welcomes).toEqual(["p1"]);
    expect(h.statuses.at(-1)?.status).toBe("connected");
  });
});

describe("client → server", () => {
  it("sends monotonic-seq input frames while open", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    const controls = { thrust: true, back: false, left: false, right: false, shoot: true };
    expect(h.connection.sendInput(controls)).toBe(1);
    expect(h.connection.sendInput(controls)).toBe(2);
    const frames = h.latest().sent.map((raw) => JSON.parse(raw) as { t: string; seq: number; controls: unknown });
    expect(frames.slice(1)).toEqual([
      { t: "input", seq: 1, controls },
      { t: "input", seq: 2, controls },
    ]);
  });

  it("holds input while the socket is not open (reconnect pause)", () => {
    const h = harness();
    h.connection.connect();
    h.connection.sendInput({ thrust: false, back: false, left: false, right: false, shoot: false });
    expect(h.latest().sent).toEqual([]);
  });

  it("sends buy, click, and restart intents", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.connection.sendBuy(7);
    h.connection.sendClick(640, 360);
    h.connection.sendRestart();
    const kinds = h.latest().sent.map((raw) => JSON.parse(raw) as { t: string; slot?: number; x?: number });
    expect(kinds).toEqual([
      { t: "join", room: "ABCD", name: "Husam" },
      { t: "buy", slot: 7 },
      { t: "click", x: 640, y: 360 },
      { t: "restart" },
    ]);
  });
});

describe("server → client", () => {
  it("forwards snapshots", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.latest().serverMessage({ t: "welcome", you: "p1", tickHz: 60, snapshot: snapshotOf() });
    h.latest().serverMessage({
      t: "snapshot",
      tick: 12,
      ack: 3,
      ...snapshotOf(),
      events: [{ k: "shoot" }],
    });
    expect(h.snapshots).toHaveLength(1);
    expect(h.snapshots[0]?.tick).toBe(12);
    expect(h.snapshots[0]?.ack).toBe(3);
    expect(h.snapshots[0]?.events).toEqual([{ k: "shoot" }]);
  });

  it("ignores malformed and unknown frames without dying", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.latest().rawMessage("not json at all");
    h.latest().rawMessage(JSON.stringify({ t: "mystery" }));
    expect(h.connection.status).toBe("connecting");
    expect(h.statuses.every((entry) => entry.status !== "dropped")).toBe(true);
  });

  it("treats rejected as terminal with its reason", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.latest().serverMessage({ t: "rejected", reason: "room-full" });
    expect(h.connection.status).toBe("rejected");
    expect(h.statuses.at(-1)).toEqual({ status: "rejected", reason: "room-full" });
    vi.advanceTimersByTime(2000);
    expect(h.sockets).toHaveLength(1); // no retry storm after a rejection
  });
});

describe("reconnect state machine", () => {
  it("retries after an unexpected drop and re-joins on the new socket", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.latest().drop();
    expect(h.connection.status).toBe("reconnecting");
    vi.advanceTimersByTime(500);
    expect(h.sockets).toHaveLength(2);
    h.latest().openUp();
    const sent = h.latest().sent.map((raw) => JSON.parse(raw) as { t: string });
    expect(sent).toEqual([{ t: "join", room: "ABCD", name: "Husam" }]);
  });

  it("gives up with a dropped state after the 10 s window", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.latest().drop(); // first drop at t=0
    expect(h.connection.status).toBe("reconnecting");
    vi.advanceTimersByTime(500); // retry inside the window
    h.tickClock(10_000); // ...and keep failing past the window
    h.latest().drop();
    expect(h.connection.status).toBe("dropped");
    vi.advanceTimersByTime(5000);
    expect(h.sockets).toHaveLength(2); // the retry loop is dead
  });

  it("a healthy welcome resets the retry window", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.latest().drop(); // first drop at t=0
    vi.advanceTimersByTime(500);
    h.latest().openUp();
    h.latest().serverMessage({ t: "welcome", you: "p1", tickHz: 60, snapshot: snapshotOf() });
    h.tickClock(60_000); // a long healthy session later...
    h.latest().drop();
    expect(h.connection.status).toBe("reconnecting"); // ...a fresh window, not dropped
  });

  it("input seqs continue across reconnects", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    expect(h.connection.sendInput({ thrust: false, back: false, left: false, right: false, shoot: false })).toBe(1);
    h.latest().drop();
    vi.advanceTimersByTime(500);
    h.latest().openUp();
    expect(h.connection.sendInput({ thrust: false, back: false, left: false, right: false, shoot: false })).toBe(2);
  });

  it("ignores close events from a stale socket", () => {
    const h = harness();
    h.connection.connect();
    const first = h.latest();
    first.openUp();
    vi.advanceTimersByTime(500); // no drop, this is a manual second connect
    h.connection.connect(); // replaces the socket (generation bump)
    first.drop(); // the old socket dies late — must be ignored
    expect(h.connection.status).toBe("connecting"); // not "reconnecting"
    expect(h.sockets).toHaveLength(2);
  });

  it("close() stops everything without status churn", () => {
    const h = harness();
    h.connection.connect();
    h.latest().openUp();
    h.connection.close();
    h.latest().drop();
    vi.advanceTimersByTime(5000);
    // No welcome was ever delivered, so the status stays "connecting" —
    // the contract is that a post-close drop never reads reconnecting
    // or dropped, and no retry socket is created.
    expect(h.connection.status).toBe("connecting");
    expect(h.sockets).toHaveLength(1);
  });
});
