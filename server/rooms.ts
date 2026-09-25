/**
 * The authoritative room host. Rooms are keyed by a 4-char code, capped at
 * 4 seats, and live in memory only — a restart of the process ends every
 * match (spec: no persistence).
 *
 * Authority invariant: the server is the ONLY writer of world state. The
 * shared sim (`step`) advances one fixed tick at a time; clients send intent
 * (input, buy, click, restart) and receive snapshots at ~20 Hz with a
 * per-client input-seq ack. No client message ever writes the world directly.
 */

import {
  addPlayer,
  buy,
  clickAt,
  newWorld,
  removePlayer,
  requestRestart,
  snapshot,
  step,
} from "../shared";
import type {
  ClientMsg,
  Controls,
  GameEvent,
  ServerMsg,
  World,
} from "../shared";
import { parseClientMsg } from "./wire";

/** The one transport method a connection must offer. `ws` adapters live in
 * gateway.ts; rooms never import the transport. */
export interface RoomSocket {
  readonly id: string;
  /** Serialized ServerMsg. Implementations tolerate a closing socket. */
  send(payload: string): void;
  close(): void;
}

export interface RoomHubOptions {
  /** Sim ticks per second (fixed dt = 1/tickHz). Spec: 60. */
  tickHz?: number;
  /** Broadcast a snapshot every Nth tick. Spec: 3 → ~20 Hz. */
  broadcastEvery?: number;
  /** How long a disconnected player's seat (and ship) is held. Spec: 10 s. */
  seatTimeoutMs?: number;
  /** When false, no interval runs — tests drive tickOnce() by hand. */
  autoTick?: boolean;
  /** Per-room world seed; the server seeds each room (spec). */
  makeSeed?: () => number;
}

/** Room codes: exactly 4 chars, A–Z0–9. Join input is uppercased first. */
const ROOM_CODE_RE = /^[A-Z0-9]{4}$/;

/** Spec-locked co-op room size. */
const ROOM_CAP = 4;

const MAX_NAME_LENGTH = 16;

interface Seat {
  playerId: string;
  name: string;
  /** Live while connected; null during the disconnect-grace window. */
  socket: RoomSocket | null;
  lastSeq: number;
  lastControls: Controls | undefined;
  expiryTimer: NodeJS.Timeout | null;
}

type Intent = Exclude<ClientMsg, { t: "join" }>;

/** A seated socket's routing entry: which room, which seat. */
interface Binding {
  room: Room;
  seat: Seat;
}

/**
 * Owns every room, the tick clock, and the socket→seat bindings. One hub
 * per process; one accumulator per hub keeps the sim at exactly tickHz
 * regardless of timer jitter (bounded catch-up, like MAX_DT bounds a step).
 */
export class RoomHub {
  private readonly rooms = new Map<string, Room>();
  private readonly bindings = new Map<string, Binding>();
  private readonly tickHz: number;
  private readonly broadcastEvery: number;
  private readonly seatTimeoutMs: number;
  private readonly autoTick: boolean;
  private readonly makeSeed: () => number;
  private ticker: NodeJS.Timeout | null = null;
  private accMs = 0;
  private lastPumpAt = 0;

  constructor(options: RoomHubOptions = {}) {
    this.tickHz = options.tickHz ?? 60;
    this.broadcastEvery = options.broadcastEvery ?? 3;
    this.seatTimeoutMs = options.seatTimeoutMs ?? 10_000;
    this.autoTick = options.autoTick ?? true;
    this.makeSeed = options.makeSeed ?? defaultSeed;
  }

  /** Frame in from the transport: validate, then dispatch. A malformed
   * frame is dropped, never fatal — and an unexpected internal error is
   * surfaced to stderr rather than taking down the room. */
  handleRaw(socket: RoomSocket, data: string): void {
    const msg = parseClientMsg(data);
    if (msg === null) return; // malformed: ignore, room and socket unharmed
    try {
      this.handleMsg(socket, msg);
    } catch (error) {
      process.stderr.write(`[rooms] dropped message after internal error: ${String(error)}\n`);
    }
  }

  /** The socket left (close or error). Its seat enters the grace window;
   * the room continues either way. */
  handleClose(socket: RoomSocket): void {
    const binding = this.bindings.get(socket.id);
    if (!binding) return;
    this.bindings.delete(socket.id);
    binding.room.detach(binding.seat);
  }

  /** One fixed sim step in every room (also the manual-test entry). */
  tickOnce(): void {
    for (const room of [...this.rooms.values()]) room.tick();
  }

  getRoom(code: string): Room | undefined {
    return this.rooms.get(code);
  }

  /** Tear everything down (tests; process shutdown). */
  close(): void {
    this.stopTicking();
    for (const room of this.rooms.values()) room.dispose();
    this.rooms.clear();
    this.bindings.clear();
  }

  // -- internals ------------------------------------------------------------

  private handleMsg(socket: RoomSocket, msg: ClientMsg): void {
    if (msg.t === "join") {
      this.join(socket, msg.room, msg.name);
      return;
    }
    const binding = this.bindings.get(socket.id);
    if (!binding) return; // intent from an unseated socket: ignored
    binding.room.handleIntent(binding.seat, msg);
  }

  private join(socket: RoomSocket, roomInput: string, nameInput: string): void {
    if (this.bindings.has(socket.id)) return; // one seat per connection
    const code = roomInput.trim().toUpperCase();
    if (!ROOM_CODE_RE.test(code)) {
      this.reply(socket, { t: "rejected", reason: "bad-code" });
      return;
    }
    const name = normalizeName(nameInput);
    let room = this.rooms.get(code);
    if (!room) {
      room = this.createRoom(code);
    } else if (!room.findResumableSeat(name) && room.seatCount >= ROOM_CAP) {
      this.reply(socket, { t: "rejected", reason: "room-full" });
      return;
    }
    const seat = room.seat(socket, name);
    this.bindings.set(socket.id, { room, seat });
    this.reply(socket, { t: "welcome", you: seat.playerId, tickHz: 60, snapshot: snapshot(room.world) });
  }

  private createRoom(code: string): Room {
    const room = new Room(code, this.makeSeed(), {
      stepDt: 1 / this.tickHz,
      broadcastEvery: this.broadcastEvery,
      seatTimeoutMs: this.seatTimeoutMs,
      onEmpty: () => this.removeRoom(code),
    });
    this.rooms.set(code, room);
    this.ensureTicking();
    return room;
  }

  private removeRoom(code: string): void {
    this.rooms.delete(code);
    if (this.rooms.size === 0) this.stopTicking();
  }

  /** Lazily started (first room) and auto-stopped (last room gone) so an
   * idle hub costs nothing. */
  private ensureTicking(): void {
    if (!this.autoTick || this.ticker !== null) return;
    this.lastPumpAt = performance.now();
    this.ticker = setInterval(() => this.pump(), tickIntervalMs(this.tickHz));
    this.ticker.unref?.();
  }

  private stopTicking(): void {
    if (this.ticker !== null) {
      clearInterval(this.ticker);
      this.ticker = null;
    }
  }

  private pump(): void {
    const now = performance.now();
    const stepMs = 1000 / this.tickHz;
    // Bound catch-up at six ticks (the spec sketch's TICK*6): a stalled
    // host drops time instead of teleporting the field.
    this.accMs = Math.min(this.accMs + (now - this.lastPumpAt), stepMs * 6);
    this.lastPumpAt = now;
    while (this.accMs >= stepMs) {
      this.tickOnce();
      this.accMs -= stepMs;
    }
  }

  private reply(socket: RoomSocket, msg: ServerMsg): void {
    socket.send(JSON.stringify(msg));
  }
}

function defaultSeed(): number {
  return Math.floor(Math.random() * 0x7fffffff);
}

function tickIntervalMs(tickHz: number): number {
  // Round down: the accumulator corrects the rate, a slower interval
  // would not.
  return Math.max(1, Math.floor(1000 / tickHz));
}

function normalizeName(raw: string): string {
  const name = raw.trim().slice(0, MAX_NAME_LENGTH);
  return name.length > 0 ? name : "Player";
}

/** One room: the world (the sim owns its contents), the seats that may
 * write intent into it, and the broadcast cadence. */
export class Room {
  readonly code: string;
  /** The authoritative state. Direct access is for the hub and tests —
   * clients only ever see snapshot(). */
  readonly world: World;

  private readonly stepDt: number;
  private readonly broadcastEvery: number;
  private readonly seatTimeoutMs: number;
  private readonly onEmpty: () => void;
  private readonly seats = new Map<string, Seat>();
  private readonly pendingEvents: GameEvent[] = [];
  private tickCount = 0;
  private nextPlayerNum = 1;

  constructor(
    code: string,
    seed: number,
    opts: { stepDt: number; broadcastEvery: number; seatTimeoutMs: number; onEmpty: () => void },
  ) {
    this.code = code;
    this.world = newWorld(seed);
    this.stepDt = opts.stepDt;
    this.broadcastEvery = opts.broadcastEvery;
    this.seatTimeoutMs = opts.seatTimeoutMs;
    this.onEmpty = opts.onEmpty;
  }

  get seatCount(): number {
    return this.seats.size;
  }

  /** Seat this socket: resume its own grace-window seat by name, or take a
   * fresh ship (late joiners spawn mid-wave with the respawn grace). */
  seat(socket: RoomSocket, name: string): Seat {
    const resumable = this.findResumableSeat(name);
    if (resumable) {
      this.cancelExpiry(resumable);
      resumable.socket = socket;
      resumable.lastSeq = 0;
      resumable.lastControls = undefined;
      return resumable;
    }
    const playerId = `p${this.nextPlayerNum++}`;
    addPlayer(this.world, playerId, name);
    const seat: Seat = { playerId, name, socket, lastSeq: 0, lastControls: undefined, expiryTimer: null };
    this.seats.set(playerId, seat);
    return seat;
  }

  /** The seat a reconnecting player resumes: disconnected (socket null),
   * same name, oldest first. */
  findResumableSeat(name: string): Seat | undefined {
    for (const seat of this.seats.values()) {
      if (seat.socket === null && seat.name === name) return seat;
    }
    return undefined;
  }

  /** The socket left: hold the seat (and its ship) for the grace window. */
  detach(seat: Seat): void {
    if (seat.socket === null) return;
    seat.socket = null;
    seat.lastControls = undefined;
    seat.expiryTimer = setTimeout(() => this.expireSeat(seat), this.seatTimeoutMs);
    seat.expiryTimer.unref?.();
  }

  dispose(): void {
    for (const seat of this.seats.values()) this.cancelExpiry(seat);
  }

  /** Client intent for this seat. Input is state for the next tick;
   * buy/click/restart apply immediately — the sim's event-pump semantics
   * (direct function calls between frames, as the Python build did). The
   * sim gates every purchase through the shared Economy: a short ledger
   * changes nothing, and the returned events ride the next snapshot. */
  handleIntent(seat: Seat, msg: Intent): void {
    switch (msg.t) {
      case "input":
        seat.lastSeq = msg.seq;
        seat.lastControls = msg.controls;
        return;
      case "buy":
        this.pendingEvents.push(...buy(this.world, msg.slot));
        return;
      case "click":
        this.pendingEvents.push(...clickAt(this.world, msg.x, msg.y));
        return;
      case "restart":
        this.pendingEvents.push(...requestRestart(this.world));
        return;
    }
  }

  /** One fixed step: advance the world, then broadcast on cadence. */
  tick(): void {
    const controls: Record<string, Controls> = {};
    for (const seat of this.seats.values()) {
      if (seat.lastControls !== undefined) controls[seat.playerId] = seat.lastControls;
    }
    this.pendingEvents.push(...step(this.world, this.stepDt, controls));
    this.tickCount += 1;
    if (this.tickCount % this.broadcastEvery === 0) this.broadcast();
  }

  private broadcast(): void {
    const snap = snapshot(this.world);
    const events = this.pendingEvents.splice(0, this.pendingEvents.length);
    for (const seat of this.seats.values()) {
      if (seat.socket === null) continue;
      const msg: ServerMsg = {
        t: "snapshot",
        tick: this.tickCount,
        ack: seat.lastSeq,
        ...snap,
        events,
      };
      seat.socket.send(JSON.stringify(msg));
    }
  }

  private expireSeat(seat: Seat): void {
    seat.expiryTimer = null;
    if (seat.socket !== null) return; // resumed while the timer was pending
    this.seats.delete(seat.playerId);
    removePlayer(this.world, seat.playerId);
    if (this.seats.size === 0) this.onEmpty();
  }

  private cancelExpiry(seat: Seat): void {
    if (seat.expiryTimer !== null) {
      clearTimeout(seat.expiryTimer);
      seat.expiryTimer = null;
    }
  }
}
