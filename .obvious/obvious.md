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

The game loops at 60 FPS until the window QUIT event (or Q at the game-over screen). A player-asteroid collision costs one of three lives — the ship respawns centered with a 2s invulnerability blink — and at zero lives a game-over overlay appears (R restarts, Q quits). Kill with timeout/interrupt for headless runs.

## Local Verification

- No linter or typechecker is configured; pytest is the test suite (dev dependency in `pyproject.toml`): `uv run pytest`.
- Smoke checks that work everywhere:
  - `uv run python -m compileall -q .` — all modules compile.
  - Headless bounded run (see above); the built-in logger writes `game_state.jsonl` (per-second sprite snapshots) and `game_events.jsonl` (`asteroid_shot`, `player_hit`, plus milestone events `high_score_beaten`, `game_over`, `restart`). Verify the state log grows and asteroids spawn.
  - `uv run python .obvious/evidence/proof.py` — bounded 180-frame headless run that saves PNG screenshots to `/tmp/obv-evidence/`.
  - `uv run python .obvious/evidence/proof_f2.py` — F2 evidence: game-over overlay + respawn blink PNGs to `/tmp/obv-evidence/`.

## Codebase Map

Flat, single-app repo — all source at root (depth ≤ 2, no sub-apps):

| File | Role |
|---|---|
| `main.py` | Entry point; pygame init, sprite groups, main 60 FPS loop, collision handling reporting hits to `Game`, click-damage input and the idle destruction-diff/mint poll (idle core) |
| `economy.py` | `Economy` — the idle ledger: credits, upgrade cost curve, `mint`/`buy`, `idle_*` keys merged through F1's save loader; the ONLY writer of the ledger |
| `game.py` | `Game` — run state (score, lives, wave, phase); respawn/invulnerability grants, game-over and full-restart resets (engagement F2) |
| `constants.py` | Tunables: screen 1280x720, player, asteroid, shot parameters |
| `circleshape.py` | `CircleShape` base class (position, velocity, radius, `collides_with`) |
| `player.py` | `Player` — triangle ship, rotate/move/shoot |
| `asteroid.py` | `Asteroid` — movement, `split()` on hit |
| `asteroidfield.py` | `AsteroidField` — spawns asteroids from screen edges on a timer |
| `shot.py` | `Shot` — player bullets |
| `hud.py` | `Score` — run score + persistent high score (`game_save.json`), `points_for()` size table, `draw_hud()` overlay, `draw_game_over()` overlay |
| `logger.py` | `log_state()` / `log_event()` — JSONL state & event logging to repo root |
| `game_events.jsonl` | Committed event log from a prior run (runtime artifact) |
| `README.md` | Empty |

## Gotchas

- The game window is required for a real run; always use the SDL dummy drivers headlessly.
- `game_state.jsonl` / `game_events.jsonl` / `game_save.json` are written to the repo root at runtime (state log and save file are gitignored, events log is committed).
- Logging auto-stops after 16 seconds per run (`_MAX_SECONDS` in `logger.py`).

## Sandbox Snapshot

- **Snapshot ID:** `8pwov2fk56tv4fvcc3pv:default` (taken 2026-09-24T18:47:37Z)
- **Environment:** Python 3.13.14, uv 0.12.18, `.venv` synced with pygame 2.6.1, verified headless run.

## Local Dev Onboarding

See `.obvious/skills/local-dev/SKILL.md`. Evidence: `.obvious/evidence/` (screenshots + bounded-run script).
