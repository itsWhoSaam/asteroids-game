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

The game loops at 60 FPS until the window QUIT event (or Q at the game-over screen). A player-asteroid collision costs one of three lives — the ship respawns centered with a 2s invulnerability blink — and at zero lives a game-over overlay appears (R restarts, Q quits). Destroyed non-small asteroids have a 15% chance to drop a timed pickup: SHIELD absorbs one hit (ring on the ship), RAPID cuts the shoot cooldown ×0.4, TRIPLE fires a three-way spread — each lasts 8s (R-free retuning lives in `constants.py`). Sound effects are synthesized procedurally at startup (no binary assets) — shoot, three explosion pitches by asteroid size, pickup, game over — and `M` toggles mute (persisted in `game_save.json`; a MUTED indicator shows top-right while muted). Kill with timeout/interrupt for headless runs.

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
  - `uv run python -m tests._balance_sim` — the ten-minute balance simulation of the main loop (income vs field density per minute, purchase curve, nuke scenario); `tests/test_balance.py` pins the fast gates.

## Codebase Map

Flat, single-app repo — all source at root (depth ≤ 2, no sub-apps):

| File | Role |
|---|---|
| `main.py` | Entry point; pygame init, sprite groups, main 60 FPS loop, collision handling reporting hits to `Game`, click-damage input and the idle destruction-diff/mint poll (idle core) |
| `economy.py` | `Economy` — the idle ledger: credits, upgrade cost curve, `mint`/`buy`, `idle_*` keys merged through F1's save loader; the ONLY writer of the ledger |
| `game.py` | `Game` — run state (score, lives, wave, phase); respawn/invulnerability grants, game-over and full-restart resets (engagement F2) |
| `constants.py` | Tunables: screen 1280x720, player, asteroid, shot parameters; the `PALETTE` table (visual V1) — the single place color lives, every entity draw and fill resolves through it |
| `circleshape.py` | `CircleShape` base class (position, velocity, radius, `collides_with`) |
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
