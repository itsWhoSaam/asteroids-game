# Asteroids — with an idle-clicker layer

A pygame arcade shooter wrapped in an idle economy: destruction mints
credits, credits buy upgrades and powerups, and purchases feed back into
destruction. Nothing is lost on death — credits, upgrade levels, and
powerup access persist between sessions. The insanity layer piles on:
combo chains, hit-stop beats, a dash, boss waves, hostile saucers,
black holes, armed mines, and cursed mystery pickups.

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

The table mirrors the in-game overlay's keymap (`help_keymap()` in
`hud.py`) row for row — the same keys and actions, the same shop and
powerup tables the handlers read — so this list can't drift from what
the game answers.

| Input | Action |
|---|---|
| `W` | Thrust (accelerates along the nose; momentum coasts) |
| `S` | Retro thrust |
| `A`/`D` | Rotate |
| `Space` | Shoot |
| `Click` (mouse) | Chip the rock under the cursor |
| `1`–`4` | Shop: Nanoblade (click damage ×1.8/lvl), Fire-rate (shot cooldown ×0.88/lvl), Income (credit payouts ×1.15/lvl), Drones (auto-turret per level) |
| `7`–`0` | Powerups: Gold Rush (credit income ×5), Nuke (clear the field, full payout), Overdrive (click damage ×10), Chrono (asteroid speed ×0.5) |
| `M` | Mute / unmute (persisted) |
| `[` / `]` | Volume down / up |
| `P`/`Esc` | Pause / resume |
| `H` | Toggle this help |
| `1`/`2`/`3` | Pick mode on the start / game-over screens (Easy / Normal / Hard) |
| `D` | Toggle the daily challenge on the start / game-over screens |
| `R`/`Q` | Restart / quit (at game over, or from the pause overlay) |

The `L`/`R`-`SHIFT` dash is part of the insanity layer (below) — the
in-game overlay lists the keys above only.

## Pause and help

`P` or `Esc` pauses a live run: every world update freezes under a
dimmed PAUSED overlay that answers only resume (`P`), restart (`R`), and
quit (`Q`). The mute key stays live while paused, and the game-over
screen is unaffected by the pause flag. `H` toggles the controls list
over dimmed play — help dims, it never pauses (the world keeps moving)
— and it closes itself at game over; a fresh run always starts
help-free.

## Difficulty modes

The game boots into a **SELECT DIFFICULTY** menu — `1` Easy, `2` Normal,
`3` Hard launches the run. The same three keys appear on the game-over
screen (the prompt reads `R restart - 1/2/3 mode (NORMAL) - D daily - Q quit`), so
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

## Daily challenge

The **D** key on the start menu or the game-over screen toggles the
daily challenge — the menu shows the mode's gold `DAILY CHALLENGE`
row and the next launch (a mode pick, or `R` at game over) starts the
seeded run. The run plays exactly like the mode it launched in, with
two differences: the asteroid spawns are **seeded from the UTC calendar
date** (`YYYYMMDD`), so the same day always rolls the same spawn
sequence — timing, positions, velocities, sizes, mines — for everyone,
and a run's best score is kept **per date** (`daily_best` in
`game_save.json`). The HUD carries a small gold `DAILY CHALLENGE` tag
for the whole run; the game-over prompt shows `D daily` so the toggle
is discoverable where the run ends. Toggling `D` off returns the next
launch to the normal shared-stream spawns.

## The idle loop

Every asteroid destroyed by any source — player shots, clicks, drone
turrets, or a nuke — mints **credits** through one shared destruction
pipeline. Payouts follow the score table (small 100 / medium 50 / large
20) scaled by the Income multiplier, so income and progression share one
source of truth. Every destruction floats a yellow `+N` credit over the
wreck; a points kill — a shot, a drone turret, the boss — stacks a white
`+N pts` popup a head above it. Click-chip kills pay the credit float
alone.

**Clicking** deals chip damage instead of instant kills: a rock absorbs
~3 clicks per size tier before it dies. Chip damage shows — ink crack
webs deepen across the hull in four stages (25/50/75% of the chip
threshold), and a split resets them; the children start uncracked.
**Nanoblade** multiplies click
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
with a health bar across the top and layered armor rings that a landed
shot lights with a warm-white flash. At 70/40/15% HP it spawns two
minion asteroids each — the fight gets harder as it gets safer — and its
slow drift scales with the difficulty mode's speed multiplier. Defeating
it pays 300 points through the combo, mints credits through the ordinary
destruction ledger, and always drops exactly one pickup from the chaos
tables; it can't be click-chipped, and black holes can shove it around,
but it never leaves the arena.

**Hostile saucers.** From wave 2, saucers cross the screen with a sine
bob and fire real shots at the ship: big saucers spray 3-way spreads
(2 HP, 200 pts), small ones fire fast aimed single shots (1 HP,
1000 pts). Saucer shots cost lives and split the asteroids they hit;
saucers that cross the screen despawn unpaid.

**Black holes.** From wave 3 (never during a boss wave), a gravity
well opens for 12 s and pulls rocks, shots, saucers, and the ship with
inverse-falloff acceleration. It kills nothing directly — the danger
is eaten agency and drifted trajectories.

**Mine asteroids.** About 6% of the field's spawns are armed mines —
dark-hulled rocks that fly exactly like their host but wear a blinking
red danger marker. A shot kill detonates one (player, drone, or saucer
fire): asteroids inside the 110 px blast pay through the ordinary seams
— plain rocks split and mint, the boss soaks one HP — and the ship
inside takes a standard hit, invulnerability honored. A mine caught in a
neighbor's blast dies without arming its own, so blasts never chain, and
a click-chip kill doesn't detonate — only shots do.

**Chaos pickups.** Destroyed non-small asteroids have a 15% chance to
drop a pickup, and 40% of drops are a violet `?` mystery pickup whose
contents roll only on collect: 75% an equal draw from the seven buffs —
**SHIELD** absorbs one hit, **RAPID** cuts the shot cooldown ×0.4,
**TRIPLE** fires a three-way spread, **PIERCE** drills shots through
rocks, **HOMING** steers them at the nearest rock, **BOMB** clears the
field through the normal pipeline (credits pay, the combo doesn't), and
**MAGNET** bends drifting pickups and credit floats toward the ship (a
force on their velocity, never a teleport — closer bodies pull harder,
capped so nothing slams past the hull; an active magnet shows a
`MAGNET Ns` tag top-right) — and 25% a curse, either REVERSE (flips the
controls for 6 s) or DISARM (strips the shield and every running effect
on reveal). Timed effects last 8 s; tuning lives at the end of
`constants.py` (`POWERUP_*`, including `POWERUP_MAGNET_*`, and the
`INSANITY` block).

## Sound

Every sound effect is synthesized at startup from stdlib `array`/`math`
— no binary assets — and any mixer failure degrades the whole bank to a
silent no-op. The core set is a shoot chirp, three explosion pitches
sized to the rock, a pickup jingle, and a game-over tone; the insanity
layer cues the dash, a combo break, saucers, the boss, black holes, and
the curse sting — plus a pew when a drone turret fires, a buzz when the
shop refuses an unaffordable purchase, and a rising four-note arpeggio
when a wave clears.

**Master volume.** `[` steps the level down, `]` up — 0–100% in 10%
steps, 100% on a fresh install. Every effect and the ambient loop scale
by the level at playback, a `VOL N%` tag sits top-right beside the
MUTED indicator, and the level persists in `game_save.json` (`volume`
key). `M` silences playback without erasing the level — unmuting
restores it.

## Ambient music

A low synthesized loop breathes under gameplay: a 55 Hz bass heartbeat
every 2 s under sparse detuned pad tones (an A2 pair beating at 0.25 Hz
and its fifth) that trade places across the loop. It's built at startup
from stdlib `array`/`math` — the same procedural builder as the SFX, no
binary assets — and loops seamlessly: every voice completes whole cycles
across the 8 s buffer, so the wrap never clicks. It plays only during a
live run (the menu and the game-over screen stay silent — a paused run
keeps breathing), and it follows the same audio seams as the SFX:
`[` / `]` scale it, `M` silences it, and any mixer failure degrades it
to a no-op. Tuning lives at the end of `constants.py` (`MUSIC_*`).

## Near-miss graze bonus

Dodging pays: a rock crossing the **graze band** — outside the collision
radius, inside collision + 24 px — while both bodies move at a meaningful
speed awards **25 points** with a white `+25 pts` popup at the near-miss
site. A per-pair cooldown (3 s) stops hover-farming, and the bonus never
triggers while the ship is invulnerable (the respawn blink and the dash
i-frames ride one timer). Score only — no credits, no combo. Tuning
lives at the end of `constants.py` (`GRAZE_*`).

## Run summary

The game-over screen reports more than the final score: a summary block
under the game-over lines shows the run's shot accuracy (`Shots: X/Y
hit (Z%)`), rocks destroyed by tier, waves survived, and credits earned
with their idle/click split. It is per-run state — never persisted —
and both restart hooks start it fresh.

## Achievements

Five lifetime awards persist across sessions: using your first nuke,
reaching wave 5, scoring 10,000 points in one run, deploying your first
drone, and beating the high score. Each unlock slides a toast into the
free top-center seat — one at a time, first-in-first-out — where it
holds for 3 s (the slides included) before releasing the seat to the
next. Unlocked ids persist in `game_save.json` (`achievements` key).

## Persistence

Everything rides in one shared file, `game_save.json` (written to the
working directory):

- `high_score` — persistent high score (written the moment it's beaten);
  the overall best across difficulty modes
- `high_score_easy` / `high_score_normal` / `high_score_hard` — per-mode
  bests (a mode's key appears the first time that mode scores)
- `difficulty` — the selected mode for the next run
- `daily_best` — the daily challenge's best score per date
  (`{"YYYY-MM-DD": score}`)
- `achievements` — the unlocked lifetime awards' ids
- `muted` — sound preference
- `volume` — master level 0–100 (`[` / `]` step it)
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
