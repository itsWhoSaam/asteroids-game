# Asteroids — with an idle-clicker layer

A pygame arcade shooter wrapped in an idle economy: destruction mints
credits, credits buy upgrades and powerups, and purchases feed back into
destruction. Nothing is lost on death — credits, upgrade levels, and
powerup access persist between sessions.

## Running the game

```bash
uv sync          # install dependencies (Python 3.13, pygame 2.6.1)
uv run main.py   # requires a display
```

Headless (sandbox/CI — no display needed):

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run main.py
```

The loop runs at 60 FPS. Quit with the window close button, or Q at the
game-over screen. Down to your last life, the HUD lives line pulses and
a red vignette rims the screen edges until the run ends — the cue that
the next hit is fatal.

## Controls

| Input | Action |
|---|---|
| `W`/`A`/`S`/`D` | Thrust and rotate the ship |
| `Space` | Shoot (instant-kill shots; cooldown scales with Fire-rate levels) |
| Mouse click | Chip the rock under the cursor — the clicker verb |
| `1`–`4` | Buy shop upgrades: Nanoblade, Fire-rate, Income, Drones (during a run) |
| `1`/`2`/`3` | Pick Easy / Normal / Hard on the start menu or the game-over screen — the choice launches the run and persists |
| `7`–`0` | Fire bought powerups: Gold Rush, Nuke, Overdrive, Chrono |
| `R` | Restart (at game over, or from the pause overlay) |
| `Q` | Quit (at game over, or from the pause overlay) |
| `P`/`Esc` | Pause/resume the run — the world freezes under a dimmed PAUSED overlay |
| `H` | Toggle the controls overlay — every key listed over dimmed play |
| `M` | Mute/unmute (persisted, works while paused) |

## Difficulty modes

The game boots into a **SELECT DIFFICULTY** menu — `1` Easy, `2` Normal,
`3` Hard launches the run. The same three keys appear on the game-over
screen (the prompt reads `R restart - 1/2/3 mode (…) - Q quit`), so
switching difficulty never leaves the end-of-run flow. `R` always
restarts the current mode.

| Mode | Lives | Spawns | Rock speed |
|---|---|---|---|
| Easy | 5 | 25% sparser | 20% slower |
| Normal | 3 | the shipped tuning | the shipped tuning |
| Hard | 2 | 20% denser | 25% faster |

The mode's multipliers scale the wave curve (`wave_params`) — cadence
and speed bands keep tightening per wave inside each mode. High scores
are tracked **per mode** (`high_score_easy` / `_normal` / `_hard`); the
legacy `high_score` key keeps its meaning as the overall best and still
migrates old saves into Normal's record. The choice persists and the
menu marks it (`< saved`) on the next boot.

## The idle loop

Every asteroid destroyed by any source — player shots, clicks, drone
turrets, or a nuke — mints **credits** through one shared destruction
pipeline. Payouts follow the score table (small 100 / medium 50 / large
20) scaled by the Income multiplier, so income and progression share one
source of truth.

**Clicking** deals chip damage instead of instant kills: a rock absorbs
~3 clicks per size tier before it dies. **Nanoblade** multiplies click
damage ×1.8 per level; **Fire-rate** cuts the shot cooldown ×0.88 per
level (floored); **Income** multiplies every payout ×1.15 per level;
**Drones** fields one auto-turret per level that fires real shots every
1.5 s — drone kills pay exactly like yours. Upgrade costs grow
exponentially (`cost = base × growth^level`), so the shop always has a
next goal.

**Powerups** are bought activations, not drops, and each use escalates
that powerup's own price ×1.25 (persisted):

| Key | Powerup | Effect | Duration |
|---|---|---|---|
| `7` | Gold Rush | Credit income ×5 | 15 s |
| `8` | Nuke | Destroys the whole on-screen field, full payout | instant |
| `9` | Overdrive | Click damage ×10 | 10 s |
| `0` | Chrono | Asteroid speed ×0.5 | 8 s |

**Time away still pays.** On launch, the time since the last session
pays out at the drone fleet's estimated rate — capped at 8 hours and
paid at half rate. A fresh install (no timestamp) grants nothing.

The core loop's pull: destruction → credits → purchases → faster
destruction. Ten minutes in, a played session out-scales the asteroid
field — the spawn cadence tightens per wave, but income compounds
faster. All balance numbers live as named constants in `constants.py`;
the values there are playtest starting points, not commitments.

**Every fifth wave pays a milestone.** Clearing waves 5, 10, 15 …
grants one shield charge plus a flat credit bonus (500 cr to start),
announced in the wave banner (`MILESTONE WAVE 5 - SHIELD +500 CR`).
The charge joins the shield pool and is kept until spent; the credits
pay the idle ledger and survive a restart. Tuning lives at the end of
`constants.py` (`MILESTONE_WAVE_INTERVAL`, `MILESTONE_SHIELD_CHARGES`,
`MILESTONE_CREDIT_BONUS`).

## Timed drops

Destroying a non-small rock has a 15% chance to drop a timed pickup —
**SHIELD** absorbs one hit, **RAPID** cuts the shot cooldown ×0.4,
**TRIPLE** fires a three-way spread, and **MAGNET** bends drifting
pickups and credit floats toward the ship (a force on their velocity,
never a teleport — closer bodies pull harder, capped so nothing slams
past the hull). Each lasts 8 seconds; an active magnet shows a
`MAGNET Ns` tag top-right. Tuning lives at the end of `constants.py`
(`POWERUP_*`, including `POWERUP_MAGNET_*`).

## Persistence

Everything rides in one shared file, `game_save.json` (written to the
working directory):

- `high_score` — persistent high score (written the moment it's beaten);
  the overall best across difficulty modes
- `high_score_easy` / `high_score_normal` / `high_score_hard` — per-mode
  bests (a mode's key appears the first time that mode scores)
- `difficulty` — the selected mode for the next run
- `muted` — sound preference
- `idle_credits`, `idle_levels`, `idle_powerup_uses`, `idle_last_seen` —
  the idle layer's ledger

Saves merge read-modify-write: each feature owns its keys and never
erases another's. Autosave runs every 30 s and on quit. A missing file
is a fresh install; a corrupt file falls back to defaults with a
warning — never a crash.

## Tests

```bash
uv run pytest
```

The suite covers the collision pipeline, waves, pickups, particles,
sound, the economy ledger, shop, drones, and powerups — including the
balance gates (a fresh save affords the first Nanoblade within 30 s of
shooting; a nuke clears the field and pays every rock exactly once).

The ten-minute balance measurement — income growth vs field density —
runs as a standalone simulation of the main loop:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run python -m tests._balance_sim
```
