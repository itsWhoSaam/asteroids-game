# QA tools — live-server probes

Operational tools for dogfooding the hosted rooms server. They talk to a
**running** server (local or hosted) over the real WebSocket protocol —
they are not unit tests and do not run in CI; `server/*.test.ts` covers
the mocked equivalents.

## probe-room.mjs

Join a room read-only and print the authoritative snapshot: seats, economy
levels, credits, asteroid field. Sends no input, so it never disturbs a
live match.

```bash
node server/qa/probe-room.mjs ws://localhost:8085/ws AB12 Probe
```

## disconnect-lifecycle.mjs

Prove disconnect hygiene end to end: seed a seat in its own throwaway
room, drop the socket, wait past the 10 s seat-expiry grace, rejoin as a
checker, and assert the seat is gone while the room still welcomes
players. Exits 0 on PASS.

```bash
node server/qa/disconnect-lifecycle.mjs ws://localhost:8085/ws 12000
```

Each run creates its own room (`T` + timestamp), so runs never interfere
with each other or with real matches.
