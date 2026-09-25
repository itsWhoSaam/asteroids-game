/**
 * The transport adapter: `ws` sockets on the `/ws` path of the same HTTP
 * server that serves the client — one origin for page and WebSocket. This
 * is the only server module that imports the transport; rooms.ts stays
 * socket-agnostic behind RoomSocket.
 */

import type { Server } from "node:http";
import { WebSocketServer, type WebSocket } from "ws";
import { RoomHub, type RoomSocket } from "./rooms";

/** Attach the room hub to an HTTP server's WebSocket upgrades. */
export function serveRooms(server: Server, hub: RoomHub): WebSocketServer {
  const wss = new WebSocketServer({ server, path: "/ws", maxPayload: 65536 });
  let nextSocketId = 1;
  wss.on("connection", (ws: WebSocket) => {
    const socket = adapt(ws, nextSocketId++);
    ws.on("message", (data) => hub.handleRaw(socket, data.toString()));
    // Error implies close is coming; handleClose is idempotent, so
    // handling both keeps the seat grace window starting immediately.
    ws.on("close", () => hub.handleClose(socket));
    ws.on("error", () => hub.handleClose(socket));
  });
  return wss;
}

function adapt(ws: WebSocket, id: number): RoomSocket {
  return {
    id: `s${id}`,
    send: (payload) => {
      try {
        ws.send(payload);
      } catch {
        // The socket is mid-close; the seat's grace window reaps it.
      }
    },
    close: () => ws.close(),
  };
}
