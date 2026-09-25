/**
 * Prove disconnect hygiene end to end against a live server:
 *
 *   1. join a fresh room as a named seat
 *   2. verify the seat exists in the welcome snapshot
 *   3. close the socket (the "page close")
 *   4. wait past the seat-expiry grace (rooms.ts holds disconnected seats
 *      for 10,000 ms)
 *   5. rejoin the room as a checker and assert the seat is gone while the
 *      room still welcomes new players
 *
 * Usage: node server/qa/disconnect-lifecycle.mjs [url] [graceMs]
 *   url     — WebSocket endpoint (default ws://localhost:8085/ws)
 *   graceMs — how long to wait for expiry (default 12000, > the 10s grace)
 *
 * Exits 0 and prints PASS when the seat is removed and the room persists;
 * exits 1 with a FAIL line otherwise. Each run creates its own throwaway
 * room, so it never disturbs a live match.
 */
import WebSocket from "ws";

const url = process.argv[2] ?? "ws://localhost:8085/ws";
const graceMs = Number(process.argv[3] ?? 12_000);
// Keep names short: the server caps name length, and a truncated name
// would not match the exact string we search for in the snapshot.
const seatName = `Gh${Date.now().toString(36).slice(-4)}`;
const roomName = `T${Date.now().toString(36).toUpperCase().slice(-3)}`;

if (!Number.isFinite(graceMs) || graceMs < 0) {
  console.error("graceMs must be a non-negative number");
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Join once, resolve with the welcome snapshot (or reject on refusal). */
function joinOnce(room, name, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    const timer = setTimeout(() => {
      ws.terminate();
      reject(new Error(`timeout waiting for welcome (${room})`));
    }, timeoutMs);
    ws.on("open", () => ws.send(JSON.stringify({ t: "join", room, name })));
    ws.on("message", (data) => {
      const m = JSON.parse(data.toString());
      if (m.t === "rejected") {
        clearTimeout(timer);
        ws.terminate();
        reject(new Error(`join rejected: ${m.reason}`));
        return;
      }
      if (m.t === "welcome") {
        clearTimeout(timer);
        ws.close();
        resolve(m);
      }
    });
    ws.on("error", (err) => {
      clearTimeout(timer);
      reject(new Error(`socket error: ${err.message}`));
    });
  });
}

// 1–2: seed the seat.
const first = await joinOnce(roomName, seatName);
const sawSeat = first.snapshot.players.some((p) => p.name === seatName);
if (!sawSeat) {
  console.error(
    `FAIL: ${seatName} missing from welcome snapshot of room ${roomName}; ` +
      `roster: ${JSON.stringify(first.snapshot.players)}`,
  );
  process.exit(1);
}
console.log(
  `SEEDED: room ${roomName} holds ${first.snapshot.players.length} seat(s); ` +
    `${seatName} present`,
);

// 3–4: drop the socket and outlive the grace window.
console.log(`CLOSED: socket dropped; waiting ${graceMs}ms for seat expiry`);
await sleep(graceMs);

// 5: the checker proves both halves of the invariant.
const check = await joinOnce(roomName, `Checker-${Date.now().toString(36)}`);
const ghosts = check.snapshot.players.filter((p) => p.name === seatName);
if (ghosts.length > 0) {
  console.error(
    `FAIL: ${seatName} still seated after ${graceMs}ms: ` +
      JSON.stringify(ghosts),
  );
  process.exit(1);
}
console.log(
  `PASS: ${seatName} removed within ${graceMs}ms; room ${roomName} ` +
    `still welcoming (${check.snapshot.players.length} seat(s), phase=${check.snapshot.phase})`,
);
process.exit(0);
