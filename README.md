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
| `1`–`4` | Buy shop upgrades: Nanoblade, Fire-rate, Income, Drones |
| `7`–`0` | Fire bought powerups: Gold Rush, Nuke, Overdrive, Chrono |
| `R` | Restart (at game over, or from the pause overlay) |
| `Q` | Quit (at game over, or from the pause overlay) |
| `P`/`Esc` | Pause/resume the run — the world freezes under a dimmed PAUSED overlay |
| `H` | Toggle the controls overlay — every key listed over dimmed play |
| `M` | Mute/unmute (persisted, works while paused) |

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

## Persistence

Everything rides in one shared file, `game_save.json` (written to the
working directory):

- `high_score` — persistent high score (written the moment it's beaten)
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
