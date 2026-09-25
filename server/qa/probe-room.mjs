/**
 * Join a room read-only and print a compact snapshot of the authoritative
 * state: players, economy levels, credits, and the asteroid field.
 *
 * Usage: node server/qa/probe-room.mjs [url] [room] [name]
 *   url  — WebSocket endpoint (default ws://localhost:8085/ws)
 *   room — 4-char room code (required: probe exits non-zero without one)
 *   name — seat name (default "Probe")
 *
 * Exits 0 after printing one snapshot; non-zero on reject, socket error,
 * or timeout. Sends no input, so it never disturbs the match.
 */
import WebSocket from "ws";

const url = process.argv[2] ?? "ws://localhost:8085/ws";
// No room passed: probe a fresh throwaway room (join creates it) so a
// one-shot probe never disturbs a live match.
const room = process.argv[3] ?? `P${Date.now().toString(36).toUpperCase().slice(-3)}`;
const name = process.argv[4] ?? "Probe";

if (room.length !== 4) {
  console.error(`room code must be 4 characters, got "${room}"`);
  process.exit(1);
}

const ws = new WebSocket(url);
let snapshotCount = 0;

ws.on("open", () => {
  ws.send(JSON.stringify({ t: "join", room, name }));
});

ws.on("message", (data) => {
  const m = JSON.parse(data.toString());
  snapshotCount += 1;

  if (m.t === "rejected") {
    console.log(`REJECTED: ${m.reason}`);
    process.exit(0);
  }

  // The welcome carries the first full snapshot; later snapshots are deltas
  // of the same shape — one is all a probe needs.
  if (m.t === "welcome" || (m.t === "snapshot" && snapshotCount > 1)) {
    const s = m.snapshot ?? m;
    console.log(
      (m.t === "welcome" ? `WELCOME you=${m.you} ` : "SNAPSHOT ") +
        `tick=${s.tick} phase=${s.phase} wave=${s.wave} ` +
        `credits=${s.economy?.credits}`,
    );
    console.log(
      "PLAYERS: " +
        JSON.stringify(
          s.players.map((p) => ({
            id: p.id,
            name: p.name,
            lives: p.lives,
            x: Math.round(p.x),
            y: Math.round(p.y),
            rot: Math.round(p.rotation),
            invuln: Math.round(p.invulnTimer * 10) / 10,
          })),
        ),
    );
    console.log("LEVELS: " + JSON.stringify(s.economy?.levels));
    console.log(
      "ASTEROIDS: " +
        JSON.stringify(
          (s.asteroids ?? []).map((a) => ({
            x: Math.round(a.x),
            y: Math.round(a.y),
            r: Math.round(a.radius),
            hp: a.chipHp,
          })),
        ),
    );
    process.exit(0);
  }
});

ws.on("error", (err) => {
  console.error(`WS ERROR: ${err.message}`);
  process.exit(1);
});

setTimeout(() => {
  console.error("TIMEOUT: no snapshot within 8s");
  process.exit(1);
}, 8000);
