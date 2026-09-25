/**
 * Rooms-server behavior, end to end: fake WS clients against a real
 * server (real HTTP + WebSocketServer via serveRooms) on an ephemeral
 * port. The hub runs with autoTick disabled so tests drive the fixed
 * tick by hand — deterministic cadence, no sleeps on the sim path —
 * except the disconnect-grace and real-tick tests, which use the clock.
 */

import { describe, expect, it } from "vitest";
import { createServer } from "node:http";
import { WebSocket } from "ws";
import {
  ASTEROID_MAX_RADIUS,
  PLAYER_START_LIVES,
  SCREEN_WIDTH,
} from "../shared";
import type { ClientMsg, PlayerState, ServerMsg } from "../shared";
import { RoomHub, type Room, type RoomHubOptions } from "./rooms";
import { serveRooms } from "./gateway";

// ---------------------------------------------------------------------------
// Fake client + server harness
// ---------------------------------------------------------------------------

type SnapshotMsg = Extract<ServerMsg, { t: "snapshot" }>;
type WelcomeMsg = Extract<ServerMsg, { t: "welcome" }>;

class FakeClient {
  private readonly ws: WebSocket;
  /** Test-visible so cadence tests can assert the queue stayed empty. */
  queue: ServerMsg[] = [];
  private waiter: ((msg: ServerMsg) => void) | null = null;

  private constructor(ws: WebSocket) {
    this.ws = ws;
    ws.on("message", (data) => {
      const msg = JSON.parse(String(data)) as ServerMsg;
      if (msg.t === "snapshot") {
        // Drop stale queued snapshots — a full-state broadcast supersedes
        // its predecessors, exactly what a real client renders from.
        this.queue = this.queue.filter((m) => m.t !== "snapshot");
      }
      const waiter = this.waiter;
      if (waiter) {
        this.waiter = null;
        waiter(msg);
      } else {
        this.queue.push(msg);
      }
    });
  }

  static connect(port: number): Promise<FakeClient> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}/ws`);
      ws.on("open", () => resolve(new FakeClient(ws)));
      ws.on("error", reject);
    });
  }

  send(msg: ClientMsg): void {
    this.ws.send(JSON.stringify(msg));
  }

  sendRaw(text: string): void {
    this.ws.send(text);
  }

  /** Next server message (queued or future), failing fast instead of hanging. */
  async next(timeoutMs = 2000): Promise<ServerMsg> {
    const queued = this.queue.shift();
    if (queued) return queued;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.waiter = null;
        reject(new Error("timed out waiting for a server message"));
      }, timeoutMs);
      this.waiter = (msg) => {
        clearTimeout(timer);
        resolve(msg);
      };
    });
  }

  async nextSnapshot(timeoutMs?: number): Promise<SnapshotMsg> {
    for (;;) {
      const msg = await this.next(timeoutMs);
      if (msg.t === "snapshot") return msg;
    }
  }

  async join(room: string, name: string): Promise<WelcomeMsg> {
    this.send({ t: "join", room, name });
    for (;;) {
      const msg = await this.next();
      if (msg.t === "welcome") return msg;
      if (msg.t === "rejected") throw new Error(`unexpected rejection: ${msg.reason}`);
    }
  }

  close(): void {
    this.ws.close();
  }

  /** Send an intent and give it time to reach the server: a synchronous
   * tick right after a raw send races the frame, which is still in flight. */
  async sendIntent(msg: ClientMsg): Promise<void> {
    this.send(msg);
    await sleep(20);
  }
}

interface ServerEnv {
  hub: RoomHub;
  port: number;
  close(): Promise<void>;
}

async function startServer(hubOptions: RoomHubOptions = {}): Promise<ServerEnv> {
  const hub = new RoomHub(hubOptions);
  const server = createServer();
  const wss = serveRooms(server, hub);
  await new Promise<void>((resolve) => server.listen(0, () => resolve()));
  const address = server.address();
  if (typeof address !== "object" || address === null) throw new Error("server has no address");
  return {
    hub,
    port: address.port,
    close: async () => {
      // Destroy sockets outright: a graceful close handshake leaves the HTTP
      // server waiting for upgraded WebSocket connections to drain.
      for (const client of wss.clients) client.terminate();
      wss.close();
      hub.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
}

// ---------------------------------------------------------------------------
// White-box helpers (the hub exposes rooms/world for precisely this)
// ---------------------------------------------------------------------------

function requireRoom(hub: RoomHub, code: string): Room {
  const room = hub.getRoom(code);
  if (!room) throw new Error(`room ${code} missing`);
  return room;
}

function playerOf(room: Room, playerId: string): PlayerState {
  const player = room.world.players[playerId];
  if (!player) throw new Error(`player ${playerId} missing from the world`);
  return player;
}

/** Burn `times` lives by collision: zero the grace window, drop a rock on
 * the ship, tick. The rock is removed between burns so the next burn finds
 * the respawned ship at the center. */
function burnLives(room: Room, playerId: string, times: number): void {
  for (let i = 0; i < times; i++) {
    const player = playerOf(room, playerId);
    player.invulnerabilityTimer = 0;
    room.world.asteroids.push({
      id: room.world.nextEntityId++,
      x: player.x,
      y: player.y,
      vx: 0,
      vy: 0,
      radius: 50,
      chipDamage: 0,
    });
    room.tick();
    room.world.asteroids.pop();
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------------------
// Room lifecycle: join → welcome → snapshots
// ---------------------------------------------------------------------------

describe("room lifecycle", () => {
  it("welcomes two clients into one room with distinct seats", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      const b = await FakeClient.connect(env.port);
      const welcomeA = await a.join("ROOM", "Ada");
      const welcomeB = await b.join("ROOM", "Bram");

      expect(welcomeA.you).not.toBe(welcomeB.you);
      expect(welcomeA.tickHz).toBe(60);
      expect(welcomeA.snapshot.phase).toBe("playing");
      expect(welcomeA.snapshot.players).toHaveLength(1); // alone at join time
      expect(welcomeB.snapshot.players).toHaveLength(2); // the second welcome sees both
      const ids = welcomeB.snapshot.players.map((p) => p.id);
      expect(ids).toContain(welcomeA.you);
      expect(ids).toContain(welcomeB.you);
      a.close();
      b.close();
    } finally {
      await env.close();
    }
  });

  it("normalizes lowercase join codes to the room", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      await a.join("r7xm", "Ada");
      expect(env.hub.getRoom("R7XM")).toBeDefined();
      a.close();
    } finally {
      await env.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Rejections: bad-code and room-full
// ---------------------------------------------------------------------------

describe("rejections", () => {
  it.each(["ABC", "ABCDE", "AB!", "", "RO MS"])("rejects malformed code %j as bad-code", async (code) => {
    const env = await startServer({ autoTick: false });
    try {
      const client = await FakeClient.connect(env.port);
      client.send({ t: "join", room: code, name: "Ada" });
      const msg = await client.next();
      expect(msg).toEqual({ t: "rejected", reason: "bad-code" });
      expect(env.hub.getRoom(code.trim().toUpperCase())).toBeUndefined(); // no room was created
      client.close();
    } finally {
      await env.close();
    }
  });

  it("rejects a fifth distinct player with room-full but keeps serving the seated four", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const clients: FakeClient[] = [];
      for (const name of ["P1", "P2", "P3", "P4"]) {
        const client = await FakeClient.connect(env.port);
        clients.push(client);
        await client.join("FULL", name);
      }
      const fifth = await FakeClient.connect(env.port);
      fifth.send({ t: "join", room: "FULL", name: "P5" });
      const msg = await fifth.next();
      expect(msg).toEqual({ t: "rejected", reason: "room-full" });

      // The room is unharmed: the seated clients still receive snapshots.
      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      const snap = await clients[0]!.nextSnapshot();
      expect(snap.players).toHaveLength(4);
      for (const client of clients) client.close();
      fifth.close();
    } finally {
      await env.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Tick + broadcast cadence + input ack (the protocol round trip)
// ---------------------------------------------------------------------------

describe("tick, broadcast, and input ack", () => {
  it("broadcasts one snapshot per client every 3rd tick, with tick and ack", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      const b = await FakeClient.connect(env.port);
      await a.join("SYNC", "Ada");
      await b.join("SYNC", "Bram");

      env.hub.tickOnce();
      env.hub.tickOnce();
      const queuedA = a.queue.length; // no snapshots yet (cadence: every 3rd tick)
      const queuedB = b.queue.length;
      env.hub.tickOnce();

      const snapA = await a.nextSnapshot();
      const snapB = await b.nextSnapshot();
      expect(queuedA).toBe(0);
      expect(queuedB).toBe(0);
      expect(snapA.tick).toBe(3);
      expect(snapA.ack).toBe(0);
      expect(snapA.players).toHaveLength(2);
      expect(snapB.tick).toBe(3); // same room tick for everyone

      // Each fake client exchanged at least one snapshot in the room.
      expect(snapA.wave).toBe(1);
      expect(snapB.wave).toBe(1);
      a.close();
      b.close();
    } finally {
      await env.close();
    }
  });

  it("acks the last input seq and applies the controls to that ship", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      const welcome = await a.join("MOVE", "Ada");
      const y0 = welcome.snapshot.players[0]!.y;

      await a.sendIntent({ t: "input", seq: 42, controls: { thrust: true, back: false, left: false, right: false, shoot: false } });
      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      const snap = await a.nextSnapshot();
      expect(snap.ack).toBe(42);
      const ship = snap.players.find((p) => p.id === welcome.you)!;
      expect(ship.y).toBeGreaterThan(y0); // rotation 0 faces up: thrust advances y
      a.close();
    } finally {
      await env.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Purchases + restart through the shared sim
// ---------------------------------------------------------------------------

describe("purchases + restart", () => {
  it("gates a buy through the shared Economy and reports the purchase event", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      await a.join("SHOP", "Ada");
      const room = requireRoom(env.hub, "SHOP");
      room.world.economy.credits = 10_000;

      await a.sendIntent({ t: "buy", slot: 1 });
      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      const snap = await a.nextSnapshot();
      expect(snap.economy.levels.nanoblade).toBe(1);
      expect(snap.economy.credits).toBeLessThan(10_000);
      expect(snap.events).toContainEqual({ k: "purchase", what: "nanoblade" });
      a.close();
    } finally {
      await env.close();
    }
  });

  it("declines a buy the ledger cannot afford (no event, no change)", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      await a.join("POOR", "Ada");
      const room = requireRoom(env.hub, "POOR");
      const credits = room.world.economy.credits; // 0: nothing is affordable

      await a.sendIntent({ t: "buy", slot: 1 });
      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      const snap = await a.nextSnapshot();
      expect(snap.economy.levels.nanoblade).toBe(0);
      expect(snap.economy.credits).toBe(credits);
      expect(snap.events.some((e) => e.k === "purchase")).toBe(false);
      a.close();
    } finally {
      await env.close();
    }
  });

  it("routes click-to-chip at the rock the client named", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      await a.join("CHIP", "Ada");
      const room = requireRoom(env.hub, "CHIP");
      // A max-tier rock: one click chips it without destroying it.
      room.world.asteroids.push({
        id: room.world.nextEntityId++,
        x: 100,
        y: 100,
        vx: 0,
        vy: 0,
        radius: ASTEROID_MAX_RADIUS,
        chipDamage: 0,
      });

      await a.sendIntent({ t: "click", x: 100, y: 100 });
      expect(room.world.asteroids[0]!.chipDamage).toBeGreaterThan(0); // applied immediately
      expect(room.world.asteroids).toHaveLength(1); // max tier survives one click
      a.close();
    } finally {
      await env.close();
    }
  });

  it("re-seeds the room on restart after an all-dead game over", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      const b = await FakeClient.connect(env.port);
      await a.join("SEED", "Ada");
      await b.join("SEED", "Bram");
      const room = requireRoom(env.hub, "SEED");

      burnLives(room, "p1", PLAYER_START_LIVES);
      expect(room.world.phase).toBe("playing"); // B is still alive: the run continues

      burnLives(room, "p2", PLAYER_START_LIVES);
      expect(room.world.phase).toBe("game_over"); // everyone out
      room.world.economy.credits = 333; // the ledger survives the restart

      await b.sendIntent({ t: "restart" }); // any player may trigger it
      for (let i = 0; i < 3; i++) env.hub.tickOnce();
      // Let the post-restart broadcast land: it supersedes the queued
      // game-over snapshot from the burn ticks (stale full state).
      await sleep(30);
      const snap = await a.nextSnapshot();
      expect(snap.phase).toBe("playing");
      expect(snap.wave).toBe(1);
      expect(snap.players.every((p) => p.lives === PLAYER_START_LIVES)).toBe(true);
      expect(snap.asteroids).toHaveLength(0);
      expect(snap.economy.credits).toBe(333);
      expect(snap.events).toContainEqual({ k: "waveStarted", wave: 1 });

      // The re-seeded field spawns again.
      for (let i = 0; i < 60; i++) env.hub.tickOnce();
      expect(room.world.asteroids.length).toBeGreaterThan(0);
      a.close();
      b.close();
    } finally {
      await env.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Disconnect hygiene
// ---------------------------------------------------------------------------

describe("disconnect hygiene", () => {
  it("holds the seat during the grace window, then removes the ship while the room continues", async () => {
    const env = await startServer({ autoTick: false, seatTimeoutMs: 150 });
    try {
      const a = await FakeClient.connect(env.port);
      const b = await FakeClient.connect(env.port);
      const welcomeA = await a.join("GONE", "Ada");
      await b.join("GONE", "Bram");
      const room = requireRoom(env.hub, "GONE");

      a.close();
      expect(room.world.players[welcomeA.you]).toBeDefined(); // seat held

      await sleep(250); // past the 150 ms grace
      expect(room.world.players[welcomeA.you]).toBeUndefined(); // ship gone
      expect(env.hub.getRoom("GONE")).toBeDefined(); // room continues for Bram

      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      const snap = await b.nextSnapshot();
      expect(snap.players.map((p) => p.id)).not.toContain(welcomeA.you);
      b.close();
    } finally {
      await env.close();
    }
  });

  it("re-welcomes a rejoin within the grace window with the same seat and ship state", async () => {
    const env = await startServer({ autoTick: false, seatTimeoutMs: 500 });
    try {
      const a = await FakeClient.connect(env.port);
      const welcomeA = await a.join("BACK", "Ada");
      const room = requireRoom(env.hub, "BACK");
      const ship = playerOf(room, welcomeA.you);
      ship.x = 555; // a recognizable ship state
      ship.score = 77;

      a.close();
      await sleep(100); // inside the window

      const again = await FakeClient.connect(env.port);
      const welcome = await again.join("BACK", "Ada");
      expect(welcome.you).toBe(welcomeA.you); // same seat
      const resumed = welcome.snapshot.players.find((p) => p.id === welcome.you)!;
      expect(resumed.x).toBe(555);
      expect(resumed.score).toBe(77);
      expect(welcome.snapshot.players).toHaveLength(1); // no duplicate ship
      expect(room.seatCount).toBe(1);
      again.close();
    } finally {
      await env.close();
    }
  });

  it("treats a rejoin after expiry as a fresh late joiner with a new ship", async () => {
    const env = await startServer({ autoTick: false, seatTimeoutMs: 120 });
    try {
      const a = await FakeClient.connect(env.port);
      await a.join("LATE", "Ada");
      const room = requireRoom(env.hub, "LATE");
      a.close();

      await sleep(250); // grace expired: seat removed, room deleted

      const again = await FakeClient.connect(env.port);
      const welcome = await again.join("LATE", "Ada");
      const freshRoom = env.hub.getRoom("LATE");
      expect(freshRoom).toBeDefined();
      expect(freshRoom).not.toBe(room); // a brand-new room instance
      const ship = welcome.snapshot.players.find((p) => p.id === welcome.you)!;
      expect(ship.lives).toBe(PLAYER_START_LIVES);
      expect(ship.invulnTimer).toBeGreaterThan(0); // fresh ship, grace window
      expect(ship.x).toBe(SCREEN_WIDTH / 2); // spawned at the center, mid-wave
      again.close();
    } finally {
      await env.close();
    }
  });

  it("hands late joiners a full snapshot of the live field", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      await a.join("MIDW", "Ada");
      const room = requireRoom(env.hub, "MIDW");
      room.world.asteroids.push({
        id: room.world.nextEntityId++,
        x: 400,
        y: 300,
        vx: 10,
        vy: 0,
        radius: 40,
        chipDamage: 0,
      });

      const b = await FakeClient.connect(env.port);
      const welcome = await b.join("MIDW", "Bram");
      expect(welcome.snapshot.players).toHaveLength(2);
      expect(welcome.snapshot.asteroids).toHaveLength(1); // the live rock is visible
      const ship = welcome.snapshot.players.find((p) => p.id === welcome.you)!;
      expect(ship.invulnTimer).toBeGreaterThan(0); // spawned with the grace window
      a.close();
      b.close();
    } finally {
      await env.close();
    }
  });

  it("deletes a memory-only room once its last seat expires", async () => {
    const env = await startServer({ autoTick: false, seatTimeoutMs: 120 });
    try {
      const a = await FakeClient.connect(env.port);
      await a.join("EVAP", "Ada");
      a.close();
      await sleep(250);
      expect(env.hub.getRoom("EVAP")).toBeUndefined();
    } finally {
      await env.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Malformed protocol: nothing crashes a room
// ---------------------------------------------------------------------------

describe("malformed protocol", () => {
  it("ignores garbage frames and unknown intents, then keeps serving", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      const b = await FakeClient.connect(env.port);
      await a.join("FRAG", "Ada");
      await b.join("FRAG", "Bram");

      a.sendRaw("not json at all");
      a.sendRaw('"just a string"');
      a.sendRaw("123");
      a.sendRaw('{"t":"bogus"}');
      a.sendRaw('{"t":"input"}'); // input without seq
      a.sendRaw('{"t":"input","seq":"x","controls":{}}'); // non-numeric seq
      a.sendRaw('{"t":"buy","slot":5}'); // not a shop slot
      a.sendRaw('{"t":"buy","slot":"1"}'); // wrong type
      a.sendRaw('{"t":"click","x":"left","y":0}'); // wrong type
      a.sendRaw("null"); // JSON null: parses, then fails the object check

      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      const snapA = await a.nextSnapshot();
      const snapB = await b.nextSnapshot();
      expect(snapA.players).toHaveLength(2); // the room never noticed
      expect(snapB.players).toHaveLength(2);

      // A valid input still flows after the barrage.
      await a.sendIntent({ t: "input", seq: 7, controls: { thrust: false, back: false, left: false, right: false, shoot: false } });
      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      expect((await a.nextSnapshot()).ack).toBe(7);
      a.close();
      b.close();
    } finally {
      await env.close();
    }
  });

  it("ignores intents from an unseated socket and still seats its join", async () => {
    const env = await startServer({ autoTick: false });
    try {
      const a = await FakeClient.connect(env.port);
      a.send({ t: "input", seq: 1, controls: { thrust: false, back: false, left: false, right: false, shoot: false } });
      a.send({ t: "buy", slot: 1 });
      a.send({ t: "click", x: 0, y: 0 });
      a.send({ t: "restart" });

      const welcome = await a.join("SEAT", "Ada"); // join still works after
      expect(welcome.you).toBe("p1");

      // A second join on the same socket is ignored (one seat per connection).
      a.send({ t: "join", room: "SEAT", name: "Ada" });
      env.hub.tickOnce();
      env.hub.tickOnce();
      env.hub.tickOnce();
      const msg = await a.next();
      expect(msg.t).toBe("snapshot"); // not a second welcome
      a.close();
    } finally {
      await env.close();
    }
  });
});

// ---------------------------------------------------------------------------
// The real tick loop: autoTick at 60 Hz with 20 Hz broadcasts
// ---------------------------------------------------------------------------

describe("real-tick loop", () => {
  it("pushes snapshots to two joined clients under the live clock", async () => {
    const env = await startServer(); // production defaults: 60 Hz, every 3rd tick
    try {
      const a = await FakeClient.connect(env.port);
      const b = await FakeClient.connect(env.port);
      await a.join("LIVE", "Ada");
      await b.join("LIVE", "Bram");

      const snapA = await a.nextSnapshot(3000);
      const snapB = await b.nextSnapshot(3000);
      expect(snapA.players).toHaveLength(2);
      expect(snapB.players).toHaveLength(2);
      expect(snapA.tick).toBeGreaterThan(0);
      a.close();
      b.close();
    } finally {
      await env.close();
    }
  }, 10_000);
});
