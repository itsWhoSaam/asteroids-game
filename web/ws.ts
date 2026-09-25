/**
 * The room WebSocket client. Speaks only shared/protocol.ts — ServerMsg
 * down, ClientMsg up. Contract (spec: Flow and states): a drop under 10 s
 * shows a reconnect banner and retries while the server keeps the seat;
 * past 10 s it reports dropped with a plain message and returns the player
 * to the landing flow. Input seqs are monotonic; the server acks the last
 * one on every snapshot.
 *
 * Socket I/O is injected (SocketFactory) so the reconnect state machine is
 * unit-testable without a network; the default wraps the browser WebSocket.
 */
import type { ClientMsg, Controls, ServerMsg, ShopSlot, Snapshot } from "../shared/protocol";

export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "dropped" | "rejected";

export type SnapshotMsg = Extract<ServerMsg, { t: "snapshot" }>;

export interface RoomConnectionCallbacks {
  onWelcome(you: string, snapshot: Snapshot): void;
  onSnapshot(message: SnapshotMsg): void;
  onStatus(status: ConnectionStatus, reason?: "room-full" | "bad-code"): void;
}

/** Minimal surface RoomConnection needs; the real WebSocket satisfies it. */
export interface SocketLike {
  send(data: string): void;
  close(): void;
  isOpen(): boolean;
  onopen: (() => void) | null;
  onmessage: ((data: unknown) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
}

export type SocketFactory = (url: string) => SocketLike;

const RETRY_DELAY_MS = 500;
/** The server keeps the seat for 10 s; the client's retry window matches. */
const RECONNECT_WINDOW_MS = 10_000;

/** Default socket: the browser WebSocket, handlers forwarded onto the
 * SocketLike surface. */
export function wrapWebSocket(ws: WebSocket): SocketLike {
  const socket: SocketLike = {
    send: (data) => ws.send(data),
    close: () => ws.close(),
    isOpen: () => ws.readyState === WebSocket.OPEN,
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
  };
  ws.onopen = () => socket.onopen?.();
  ws.onmessage = (event) => socket.onmessage?.(event.data);
  ws.onclose = () => socket.onclose?.();
  ws.onerror = () => socket.onerror?.();
  return socket;
}

/** Light runtime guard: the wire is trusted shape-wise, but a malformed
 * frame must never take the client down. */
function isServerMsg(value: unknown): value is ServerMsg {
  if (typeof value !== "object" || value === null) return false;
  const t = (value as { t?: unknown }).t;
  return t === "welcome" || t === "snapshot" || t === "rejected";
}

export class RoomConnection {
  private socket: SocketLike | null = null;
  private socketFactory: SocketFactory;
  private seq = 0;
  private _status: ConnectionStatus = "connecting";
  private firstDropAt: number | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;
  private generation = 0;

  constructor(
    private readonly opts: {
      url: string;
      room: string;
      name: string;
      now?: () => number;
      socketFactory?: SocketFactory;
    },
    private readonly callbacks: RoomConnectionCallbacks,
  ) {
    this.socketFactory = opts.socketFactory ?? ((url) => wrapWebSocket(new WebSocket(url)));
  }

  /** Current status; transitions also fire the onStatus callback. */
  get status(): ConnectionStatus {
    return this._status;
  }

  connect(): void {
    this.generation += 1;
    const generation = this.generation;
    this.closedByUs = false;
    this.setStatus(this.firstDropAt === null ? "connecting" : "reconnecting");

    const socket = this.socketFactory(this.opts.url);
    this.socket = socket;
    socket.onopen = () => {
      if (generation !== this.generation) return; // a stale socket from a prior attempt
      this.sendNow({ t: "join", room: this.opts.room, name: this.opts.name });
    };
    socket.onmessage = (data) => {
      if (generation !== this.generation) return;
      this.handleMessage(data);
    };
    socket.onclose = () => {
      if (generation !== this.generation) return;
      this.handleDrop();
    };
    socket.onerror = () => {
      if (generation !== this.generation) return;
      this.handleDrop(); // errors are followed by close; the guard dedupes
    };
  }

  /** Deliberate teardown — no reconnect, no status change. */
  close(): void {
    this.closedByUs = true;
    this.generation += 1;
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  sendInput(controls: Controls): number {
    this.seq += 1;
    this.send({ t: "input", seq: this.seq, controls });
    return this.seq;
  }

  sendBuy(slot: ShopSlot): void {
    this.send({ t: "buy", slot });
  }

  sendClick(x: number, y: number): void {
    this.send({ t: "click", x, y });
  }

  sendRestart(): void {
    this.send({ t: "restart" });
  }

  private send(message: ClientMsg): void {
    if (this.socket?.isOpen()) this.sendNow(message);
    // While not open (reconnecting), input is paused per spec; shop and
    // restart intents during a blip are dropped — the banner says why.
  }

  private sendNow(message: ClientMsg): void {
    this.socket?.send(JSON.stringify(message));
  }

  private handleDrop(): void {
    if (this.closedByUs || this.retryTimer !== null) return;
    const now = (this.opts.now ?? Date.now)();
    if (this.firstDropAt === null) this.firstDropAt = now;
    if (now - this.firstDropAt >= RECONNECT_WINDOW_MS) {
      this.setStatus("dropped");
      return;
    }
    this.setStatus("reconnecting");
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, RETRY_DELAY_MS);
  }

  private handleMessage(data: unknown): void {
    let parsed: unknown;
    try {
      parsed = typeof data === "string" ? JSON.parse(data) : data;
    } catch (error) {
      console.warn("asteroids: malformed server frame ignored", error);
      return;
    }
    if (!isServerMsg(parsed)) {
      console.warn("asteroids: unknown server frame ignored", parsed);
      return;
    }
    switch (parsed.t) {
      case "welcome":
        this.firstDropAt = null; // healthy again
        this.setStatus("connected");
        this.callbacks.onWelcome(parsed.you, parsed.snapshot);
        break;
      case "snapshot":
        this.callbacks.onSnapshot(parsed);
        break;
      case "rejected":
        this.close();
        this.setStatus("rejected", parsed.reason);
        break;
    }
  }

  private setStatus(status: ConnectionStatus, reason?: "room-full" | "bad-code"): void {
    if (this._status === status && status !== "rejected") return;
    this._status = status;
    this.callbacks.onStatus(status, reason);
  }
}
