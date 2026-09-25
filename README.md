# Asteroids — with an idle-clicker layer

A pygame arcade shooter wrapped in an idle economy: destruction mints
credits, credits buy upgrades and powerups, and purchases feed back into
destruction. Nothing is lost on death — credits, upgrade levels, and
powerup access persist between sessions. The insanity layer piles on:
combo chains, hit-stop beats, a dash, boss waves, hostile saucers,
black holes, and cursed mystery pickups.

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
| `L`/`R`-`SHIFT` | Dash — impulse along the nose, 0.25 s of invulnerability, 2 s cooldown; breaks the combo |
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

**Powerups** are bought activations, and each use escalates that
powerup's own price ×1.25 (persisted); the field also drops pickups —
see the insanity layer:

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

## The insanity layer

Every piece rides the shared destruction pipeline — kills chain,
freeze, and pay the same way they always did.

**Combo chains.** Every asteroid destroyed by player-or-drone fire
within 3 s of the previous kill extends the chain; each kill's points
multiply by the chain (+0.25 per kill, capped at ×5). Dashing or losing
a life breaks it; a shielded hit doesn't. The HUD shows `COMBO xN (t)`
under the wave slot, and the game-over screen reports the run's top
chain and best multiplier. Combos are score-only — credits mint exactly
as they always did.

**Hit-stop.** Every destruction freezes the whole simulation for a
50–90 ms beat (longer when several rocks die in one frame), so kills
land with weight. The freeze ticks on real time and always ends.

**Dash.** `L/R-SHIFT` fires an impulse along the nose with 0.25 s of
invulnerability — the ship blinks, exactly like a respawn grace — on a
2 s cooldown. It's the panic button, and it prices itself: dashing
breaks the combo.

**Boss waves.** Every fifth wave fields one boss: a huge multi-hit rock
with a health bar across the top. At 70/40/15% HP it spawns two minion
asteroids each — the fight gets harder as it gets safer. A boss pays
300 points through the combo, never mints credits, and can't be
click-chipped; black holes can shove it around, but it never leaves
the arena.

**Hostile saucers.** From wave 2, saucers cross the screen with a sine
bob and fire real shots at the ship: big saucers spray 3-way spreads
(2 HP, 200 pts), small ones fire fast aimed single shots (1 HP,
1000 pts). Saucer shots cost lives and split the asteroids they hit;
saucers that cross the screen despawn unpaid.

**Black holes.** From wave 3 (never during a boss wave), a gravity
well opens for 12 s and pulls rocks, shots, saucers, and the ship with
inverse-falloff acceleration. It kills nothing directly — the danger
is eaten agency and drifted trajectories.

**Chaos pickups.** Destroyed non-small asteroids have a 15% chance to
drop a pickup, and 40% of drops are a violet `?` mystery pickup whose
contents roll only on collect: 75% an equal draw from the six buffs
(SHIELD, RAPID, TRIPLE, PIERCE, HOMING, BOMB), 25% a curse — REVERSE
flips the controls for 6 s, DISARM strips the shield and every running
effect on reveal. Timed effects last 8 s; BOMB clears the field through
the normal pipeline (credits pay, the combo doesn't).

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
sound, the economy ledger, shop, drones, and powerups — plus the seven
insanity features (combo, hit-stop, dash, boss, saucer, black hole,
chaos pickups), each with its own test module — including the balance
gates (a fresh save affords the first Nanoblade within 30 s of
shooting; a nuke clears the field and pays every rock exactly once).

The ten-minute balance measurement — income growth vs field density,
plus the insanity pressure read (combo chains, boss/saucer/hole tempo,
chaos drops) — runs as a standalone simulation of the main loop. Pin a
seed for a reproducible session; `--json` prints a machine-readable
report and exits nonzero on broken accounting or a silent feature:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
    uv run python -m tests._balance_sim 10 --seed 20260924 --json
```
