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

The game boots into the SELECT DIFFICULTY menu (Tier 2) — the menu freezes the world the same way pause does, so a menu-only headless run writes state snapshots but spawns nothing until a mode (`1`/`2`/`3`) launches the run. The run then loops at 60 FPS until the window QUIT event (or Q at the game-over screen). A player-asteroid collision costs one of three lives — the ship respawns centered with a 2s invulnerability blink — and at zero lives a game-over overlay appears (R restarts, Q quits). The insanity layer: kills chain into a score multiplier (`COMBO xN (t)` under the wave slot, ×5 cap, 3s window — dashing or losing a life breaks the chain, a shielded hit doesn't), every destruction freezes the simulation for a 50–90ms beat, `L/R-SHIFT` dashes (impulse along the nose, 0.25s of invulnerability on the existing blink timer, 2s cooldown), every fifth wave fields a boss (HP bar top-center, minion spawns at 70/40/15%, never a credit wreck, never click-chippable, can't be culled off-screen), hostile saucers cross from wave 2 firing real shots into their own `enemy_shots` group, and black holes from wave 3 bend every trajectory through a per-frame `live_holes` registry (never during a boss wave). Destroyed non-small asteroids have a 15% chance to drop a pickup, and 40% of those drops are a violet `?` mystery pickup whose contents roll only on collect: 25% a curse (REVERSE flips the controls for 6s; DISARM strips the shield and every running effect on reveal), otherwise an equal draw from the six buffs — SHIELD absorbs one hit (ring on the ship), RAPID cuts the shoot cooldown ×0.4, TRIPLE fires a three-way spread, PIERCE lets shots drill through rocks, HOMING bends shots toward the nearest rock, BOMB clears the whole field instantly — timed effects last 8s, the reverse curse 6s (R-free retuning lives in `constants.py`). Sound effects are synthesized procedurally at startup (no binary assets) — shoot, three explosion pitches by asteroid size, pickup, game over, plus the insanity cues (dash, combo break, saucer, boss, black hole, curse sting) — and `M` toggles mute (persisted in `game_save.json`; a MUTED indicator shows top-right while muted). `P` or `Esc` pauses a live run: a paused flag gates every world update and a dimmed PAUSED overlay shows resume (P) / restart (R) / quit (Q); mute stays live while paused and the game-over screen is unaffected. Every fifth cleared wave pays a milestone — a shield charge plus a flat credit bonus — announced in the wave banner text (the grant routes through `maybe_advance_wave` with optional player/economy seams and honors the `spawned_this_wave` guard). Kill with timeout/interrupt for headless runs.

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
  - `uv run python .obvious/evidence/proof_v5.py` — visual V5 evidence: comic-HUD hero frame, game-over caption panels, banner fade strip, and audio-tag corner PNGs to `/tmp/obv-evidence/`, with panel-family pixel, MUTED-slot, fade-dimming, glyph-cache, and composite-budget self-checks asserted.
  - `uv run python .obvious/evidence/proof_milestone.py` — milestone-rewards evidence: WAVE 4 plain flash (no grant) vs the MILESTONE WAVE 5 - SHIELD +500 CR banner with the shield ring, plus the ring persisting after the flash fades, to `/tmp/obv-evidence/`, with banner text, stocked charge, and ledger bonus asserted.
  - `uv run python .obvious/evidence/proof_popups.py` — distinct-score-popups evidence: a shot kill's white `+50 pts` popup stacked a head above the yellow `+50` credit float over the same wreck, plus a chip kill paying the credit float alone (no popup without a points award), to `/tmp/obv-evidence/`, with both popup labels, colors, the offset stack, and the single mint asserted.
  - `uv run python .obvious/evidence/proof_low_lives.py` — low-lives evidence: healthy 2-lives frame, 1-life frame at rest, and pulse-peak + vignette frame PNGs to `/tmp/obv-evidence/`, with corner-blend, pulse-ink, game-over-clears, and restart-rearms self-checks asserted.
  - `uv run python .obvious/evidence/proof_cracks.py` — chip-crack evidence: a four-rock stage 0–3 strip, a real-click deepening pair (stage 1 → 3), and a two-panel split reset (chipped parent vs uncracked children) to `/tmp/obv-evidence/`, with stage-gate, strictly-deepening interior-ink, and children-read-stage-0 self-checks asserted.
  - `uv run python .obvious/evidence/proof_stats.py` — run-stats evidence: a played run's game-over summary (accuracy, tier counts, waves, credits by source) under the three-line worst-case overlay, plus a fresh zeroed summary after the R-branch restart, to `/tmp/obv-evidence/`, with counter, restart-hook, summary-wording, no-persistence, and summary-band-pixel self-checks asserted.
  - `uv run python .obvious/evidence/proof_difficulty.py` — difficulty-modes evidence: the boot SELECT DIFFICULTY menu with the saved choice marked, the Easy run's 5-lives HUD under the WAVE 1 banner, the Hard relaunch at 2 lives, and the Hard game-over prompt offering the 1/2/3 select, to `/tmp/obv-evidence/`, with menu-row, lives, spawn-cadence ordering, prompt-text, and save-key (difficulty + per-mode bests + legacy overall) self-checks asserted.
  - `uv run python -m tests._balance_sim` — the ten-minute balance simulation of the main loop (income vs field density per minute, purchase curve, nuke scenario) plus the insanity pressure read (combo chains, boss/saucer/hole tempo, chaos drops); `tests/test_balance.py` pins the fast gates. `--seed N` pins the whole session (field, drops, jitter); `--json` prints a machine-readable report and exits nonzero when a sanity check fails — accounting identities on any horizon, signs of life from every feature past 2 minutes.

## Codebase Map

Flat, single-app repo — all source at root (depth ≤ 2, no sub-apps):

| File | Role |
|---|---|
| `main.py` | Entry point; pygame init, sprite groups, main 60 FPS loop with the pause gate (`update_world` freezes all sim steps while `Game.paused`) and the hit-stop gate (`effective_frame_dt`), collision handling reporting hits to `Game`, click-damage input and the idle destruction-diff/mint poll (idle core); explicit draw passes composed in `render_world()` — action lines under entities, fx (particles + bursts) above, halftone print at screen level, HUD last (visual V4); boss/saucer/black-hole scheduling, the per-frame `blackhole.refresh_live_holes` publish, and the dash key in the event pump |
| `economy.py` | `Economy` — the idle ledger: credits, upgrade cost curve, `mint`/`buy`, `idle_*` keys merged through F1's save loader; the ONLY writer of the ledger |
| `game.py` | `Game` — run state (score, lives, wave, phase, pause flag); respawn/invulnerability grants, game-over and full-restart resets (engagement F2); owns the run-stats instance and resets it in place on restart (run-stats PR); the difficulty mode's persistence seam (`set_mode`, the pure `mode_lives` table read) applies the mode's lives at start and at both restart hooks (Tier 2); the combo meter wiring — `register_kill` pays `points × multiplier`, `break_combo` on dash/life-loss |
| `constants.py` | Tunables: screen 1280x720, player, asteroid, shot parameters; the `PALETTE` table (visual V1) — the single place color lives, every entity draw and fill resolves through it; the `INSANITY` block — combo, hit-stop, dash, boss, saucer, black-hole, and mystery tunables plus the six `SFX_*` cues |
| `circleshape.py` | `CircleShape` base class (position, velocity, radius, `collides_with`) |
| `comicfx.py` | Procedural comic FX (no assets, no dependencies): `chromatic_circle`/`chromatic_polygon` ink stacks on entities (V2); `build_background_layers()` pre-renders the action-line + halftone pair once (V4) — main blits the lines into the world under the entities and the halftone print at screen level, entity draw functions never paint background; `build_panel()` halftone plates with ink borders (V5); `cached_text`/`cached_rotated_text` — the shared `(text, color, size)` render cache and its tilted-glyph path (per-frame alpha bands scale into per-pixel coverage via BLEND_RGBA_MULT); `draw_cracks` — the seeded ink crack web over chipped rocks (Tier 2), plain `draw.lines`, headless-safe; `Burst` onomatopoeia sprite (jagged polygon + POW!/BOOM!/ZAP! pop-and-fade, 4-text cap) |
| `player.py` | `Player` — triangle ship, rotate/move/shoot; the SHIFT dash (impulse with its own decay, i-frames via `max()` on the invulnerability timer, cooldown), curse handling (REVERSE flips control signs), pierce/homing/bomb branches |
| `asteroid.py` | `Asteroid` — movement (black-hole pull + chrono scale), `split()` on hit, the `mintable`/`cullable` diff flags, click-chip state with the pure `crack_stage` gate (Tier 2) whose drawn ink web deepens with chip damage and resets on split (children start from fresh `chip_damage`); `Boss` — the fifth-wave multi-hit rock with minion checkpoints, chip immunity, and the edge-slide clamp |
| `asteroidfield.py` | `AsteroidField` — spawns asteroids from screen edges on a timer; cadence and speed band come from the pure `wave_params(wave, mode)` (engagement F3), scaled by the difficulty mode's multipliers (Tier 2), which also flags boss waves |
| `saucer.py` | `Saucer`/`SaucerShot` — hostile saucers from wave 2: cross-and-bob pathing, aimed fire into the shared shot pipeline (pure `saucer_fire_params(kind)` per kind); off-screen exit is a non-paid cull |
| `blackhole.py` | `BlackHole` — timed gravity wells; pure `accel_at`/`pull_at` falloff math, a scheduler that never opens a well during a boss wave, and the `live_holes` registry main publishes each frame |
| `powerups.py` | `PowerUp` pickups — six buffs, two mystery-only curses, and the violet `?` wildcard; pure `drops_powerup`/`drop_type`/`pick_type`/`mystery_pick_type` rolls; effect data lives in `constants.py` tables (engagement F4, insanity chaos) |
| `particles.py` | `Particle` debris + `Shake` — pure `burst_count` sizing, `burst()` spawner wired at the sweep's destruction site and in `Game.player_hit`; shake decays exponentially and offsets the draw origin only (engagement F5) |
| `shot.py` | `Shot` — player bullets; `from_drone` tags turret shots riding the same pipeline (run-stats PR); homing shots steer via a class-level targets ref (the `speed_scale` precedent), pierce rides the sweep |
| `sound.py` | Procedural SFX — stdlib `array`/`math` envelopes in `pygame.mixer.Sound`, built at startup; `play()`/`play_explosion()` degrade to a silent no-op on any mixer failure; mute state set via `set_muted` (engagement F6) |
| `stats.py` | `RunStats` — per-run counters (shots fired/hit, kills by size tier, waves survived, credits by source), pure `tier_for` banding and `summary_lines()`, in-place `reset()`; never persisted (run-stats PR) |
| `hud.py` | `Score` — run score + persistent high score (`game_save.json`), `points_for()` size table, `draw_hud()` overlay (yellow halftone panel + ink border, V5), `draw_game_over()` caption panels, `draw_run_summary()` game-over stats block (run-stats PR), `WaveBanner` flash — tilted cached glyphs, quantized per-frame alpha fade, `wave_banner_text()` milestone-announcement variant (engagement F3, visual V5, Tier 1 milestones), `LowLivesWarning` pulse + edge vignette (UX wave), the difficulty boot menu (`mode_menu_lines` pure rows + `draw_mode_menu`) and the mode-aware game-over prompt (`game_over_lines`), with per-mode high-score keys riding the save merge (Tier 2); `ComboMeter` (chain, window, milestone chirps), the DASH ready/cooling slot, and `draw_boss_bar` |
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
