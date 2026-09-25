# asteroids-game — Agent Guidance

## Stack

- **Language:** Python 3.13 (`.python-version`, `requires-python >=3.13`)
- **Framework:** pygame 2.6.1
- **Package manager:** [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`)
- **App type:** Single desktop arcade game (no server, no database, no external services, no env vars required)

## Commands

```bash
uv sync                        # install dependencies into .venv
uv run main.py                 # run the game (requires a display)
```

Headless run (sandbox/CI — no display needed):

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run main.py
```

The game loops at 60 FPS until the window QUIT event (or Q at the game-over screen). A player-asteroid collision costs one of three lives — the ship respawns centered with a 2s invulnerability blink — and at zero lives a game-over overlay appears (R restarts, Q quits). Destroyed non-small asteroids have a 15% chance to drop a timed pickup: SHIELD absorbs one hit (ring on the ship), RAPID cuts the shoot cooldown ×0.4, TRIPLE fires a three-way spread — each lasts 8s (R-free retuning lives in `constants.py`). Sound effects are synthesized procedurally at startup (no binary assets) — shoot, three explosion pitches by asteroid size, pickup, game over — and `M` toggles mute (persisted in `game_save.json`; a MUTED indicator shows top-right while muted). `P` or `Esc` pauses a live run: a paused flag gates every world update and a dimmed PAUSED overlay shows resume (P) / restart (R) / quit (Q); mute stays live while paused and the game-over screen is unaffected. Kill with timeout/interrupt for headless runs.

## Web Toolchain (multiplayer port)

Node 20 + TypeScript (strict, per-package tsconfigs for `shared/`, `server/`, `web/`) with esbuild and vitest:

```bash
npm ci                # install (package-lock.json is committed)
npm run typecheck     # tsc --noEmit across shared/, server/, web/
npm test              # vitest run
npm run build         # esbuild: web/ -> dist/ (client) + server/ -> dist-server/ (host)
npm start             # run the built room server (PORT env, default 3000)
```

The desktop Python build is untouched by the web port; `uv run pytest` remains the authoritative gate. Web checks live in the `web` job of `.github/workflows/ci.yml` alongside `pytest`, which now also triggers on the `feat/multiplayer-web-port` release branch.

## Rooms Server (server/)

The authoritative multiplayer host — Node + `ws`, memory-only rooms, one origin:

- `server/rooms.ts` — `RoomHub` (rooms keyed by 4-char codes, cap 4) and `Room` (seats, fixed 60 Hz tick advancing the shared `step()`, ~20 Hz snapshots every 3rd tick with per-client input-seq ack, 10 s disconnect grace before ship removal). Rooms vanish when their last seat expires; nothing persists.
- `server/wire.ts` — the runtime gate: untrusted frames → typed `ClientMsg` or dropped. Malformed input never reaches the sim.
- `server/gateway.ts` — the only module importing `ws`; adapts sockets to `RoomSocket` on the `/ws` path.
- `server/static.ts` — serves the built client from `dist/` on the same port (traversal-guarded).
- `server/index.ts` — entry: `npm run build && npm start` (client from `dist/` + WS at `/ws` on one port).
- Tests (`server/rooms.test.ts`, `server/static.test.ts`) run a real server on an ephemeral port with fake WS clients; the hub accepts `autoTick: false` so tests drive ticks deterministically.


## Local Verification

- No linter or typechecker is configured; pytest is the test suite (dev dependency in `pyproject.toml`): `uv run pytest`.
- Smoke checks that work everywhere:
  - `uv run python -m compileall -q .` — all modules compile.
  - Headless bounded run (see above); the built-in logger writes `game_state.jsonl` (per-second sprite snapshots) and `game_events.jsonl` (`asteroid_shot`, `player_hit`, plus milestone events `high_score_beaten`, `game_over`, `restart`, `wave_started`, `powerup_spawned`, `powerup_collected`). Verify the state log grows and asteroids spawn.
  - `uv run python .obvious/evidence/proof.py` — bounded 180-frame headless run that saves PNG screenshots to `/tmp/obv-evidence/`.
  - `uv run python .obvious/evidence/proof_f2.py` — F2 evidence: game-over overlay + respawn blink PNGs to `/tmp/obv-evidence/`.
  - `uv run python .obvious/evidence/proof_f3.py` — F3 evidence: wave banner + HUD wave-slot PNGs to `/tmp/obv-evidence/`.
  - `uv run python .obvious/evidence/proof_f4.py` — F4 evidence: pickup drop + shield-ring PNGs to `/tmp/obv-evidence/` (also logs `powerup_spawned`/`powerup_collected` to the repo-root events log).
  - `uv run python .obvious/evidence/proof_f5.py` — F5 evidence: burst before/after PNGs + a two-frame shake-offset pair to `/tmp/obv-evidence/` (offsets printed and asserted different).
  - `uv run python .obvious/evidence/proof_f6.py` — F6 evidence: unmuted/muted HUD pair (MUTED indicator top-right after a simulated M press) to `/tmp/obv-evidence/`, with mixer format, SFX table, and persisted save asserted.
  - `uv run python .obvious/evidence/proof_v1.py` — visual V1 evidence: comic-palette before/after PNGs (the before frame is a palette regrade back to white-on-black) to `/tmp/obv-evidence/`, with paper/ship/asteroid pixel self-checks asserted.
  - `uv run python .obvious/evidence/proof_v4.py` — visual V4 evidence: burst frame + lifecycle strip PNGs to `/tmp/obv-evidence/`, with word-tier, 4-text cap, fx-over-entities z-order, cache-flatness, and composite-budget self-checks asserted.
  - `uv run python -m tests._balance_sim` — the ten-minute balance simulation of the main loop (income vs field density per minute, purchase curve, nuke scenario); `tests/test_balance.py` pins the fast gates.

## Codebase Map

Flat, single-app repo — all source at root (depth ≤ 2, no sub-apps):

| File | Role |
|---|---|
| `main.py` | Entry point; pygame init, sprite groups, main 60 FPS loop with the pause gate (`update_world` freezes all sim steps while `Game.paused`), collision handling reporting hits to `Game`, click-damage input and the idle destruction-diff/mint poll (idle core); explicit draw passes composed in `render_world()` — action lines under entities, fx (particles + bursts) above, halftone print at screen level, HUD last (visual V4) |
| `economy.py` | `Economy` — the idle ledger: credits, upgrade cost curve, `mint`/`buy`, `idle_*` keys merged through F1's save loader; the ONLY writer of the ledger |
| `game.py` | `Game` — run state (score, lives, wave, phase, pause flag); respawn/invulnerability grants, game-over and full-restart resets (engagement F2) |
| `constants.py` | Tunables: screen 1280x720, player, asteroid, shot parameters; the `PALETTE` table (visual V1) — the single place color lives, every entity draw and fill resolves through it |
| `circleshape.py` | `CircleShape` base class (position, velocity, radius, `collides_with`) |
| `comicfx.py` | Procedural comic FX (no assets, no dependencies): `chromatic_circle`/`chromatic_polygon` ink stacks on entities (V2); `build_background_layers()` pre-renders the action-line + halftone pair once (V4) — main blits the lines into the world under the entities and the halftone print at screen level, entity draw functions never paint background; `Burst` onomatopoeia sprite (jagged polygon + POW!/BOOM!/ZAP! pop-and-fade, 4-text cap, `(word, color, size)` cache shared with pickups/banner) |
| `player.py` | `Player` — triangle ship, rotate/move/shoot |
| `asteroid.py` | `Asteroid` — movement, `split()` on hit |
| `asteroidfield.py` | `AsteroidField` — spawns asteroids from screen edges on a timer; cadence and speed band come from the pure `wave_params(wave)` (engagement F3) |
| `powerups.py` | `PowerUp` pickups — drifting SHIELD/RAPID/TRIPLE drops; pure `drops_powerup`/`pick_type` rolls; effect data lives in `constants.py` tables (engagement F4) |
| `particles.py` | `Particle` debris + `Shake` — pure `burst_count` sizing, `burst()` spawner wired at the sweep's destruction site and in `Game.player_hit`; shake decays exponentially and offsets the draw origin only (engagement F5) |
| `shot.py` | `Shot` — player bullets |
| `sound.py` | Procedural SFX — stdlib `array`/`math` envelopes in `pygame.mixer.Sound`, built at startup; `play()`/`play_explosion()` degrade to a silent no-op on any mixer failure; mute state set via `set_muted` (engagement F6) |
| `hud.py` | `Score` — run score + persistent high score (`game_save.json`), `points_for()` size table, `draw_hud()` overlay, `draw_game_over()` overlay, `WaveBanner` flash (engagement F3) |
| `logger.py` | `log_state()` / `log_event()` — JSONL state & event logging to repo root |
| `game_events.jsonl` | Committed event log from a prior run (runtime artifact) |
| `README.md` | Controls, idle loop, persistence, and run/test docs |

## Gotchas

- The game window is required for a real run; always use the SDL dummy drivers headlessly.
- `game_state.jsonl` / `game_events.jsonl` / `game_save.json` are written to the repo root at runtime (state log and save file are gitignored, events log is committed).
- Logging auto-stops after 16 seconds per run (`_MAX_SECONDS` in `logger.py`).

## Sandbox Snapshot

- **Snapshot ID:** `8pwov2fk56tv4fvcc3pv:default` (taken 2026-09-24T18:47:37Z)
- **Environment:** Python 3.13.14, uv 0.12.18, `.venv` synced with pygame 2.6.1, verified headless run.

## Local Dev Onboarding

See `.obvious/skills/local-dev/SKILL.md`. Evidence: `.obvious/evidence/` (screenshots + bounded-run script).
