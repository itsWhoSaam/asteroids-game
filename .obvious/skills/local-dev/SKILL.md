---
name: local-dev
description: How to get the asteroids-game running locally and verify it (from onboarding, 2026-09-24)
---

# Local Dev — asteroids-game

## Environment

- Python 3.13 via `.python-version`; manage deps with **uv** (`uv sync` creates `.venv` from `uv.lock`; pygame 2.6.1 is the only dependency).
- If uv is missing: `pip install uv`.
- No env vars, no external services, no migrations/seeding — nothing else to provision.

## Running

- GUI (needs a display): `uv run main.py`
- Headless (sandbox/CI): `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run main.py`

The game is an infinite 60 FPS loop; it exits on window close or at the game-over screen (three lives, then R restarts / Q quits). Use `timeout N` for bounded headless runs.

## Verifying (pytest is the suite — no linter is configured)

1. Compile check: `uv run python -m compileall -q .`
2. Tests: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run pytest -q`.
3. Headless bounded run; the logger writes `game_state.jsonl` (one snapshot per second for 16s: sprite counts/positions per group) and `game_events.jsonl` (`asteroid_shot`, `player_hit`). Confirm the state log fills in and asteroid counts grow.
4. Visual proof: `uv run python .obvious/evidence/proof.py` — runs 180 simulated frames and saves PNGs to `/tmp/obv-evidence/`. Committed copies live in `.obvious/evidence/`; the insanity features have their own proofs (`proof_insanity_core.py`, `proof_threats.py`, `proof_chaos.py`).
5. Balance sim: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run python -m tests._balance_sim 10 --seed 20260924 --json` — the ten-minute insanity-pressure sim; `--seed` pins the session, `--json` prints a machine-readable report and exits nonzero when a sanity check fails.

## Gotchas

- Never assume a real window exists in the sandbox — always set the SDL dummy drivers.
- `game_state.jsonl` is gitignored; `game_events.jsonl` is committed and accumulates across runs.
- Onboarding evidence (screenshots + proof script): `.obvious/evidence/`.
