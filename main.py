import blackhole
import random
from typing import NamedTuple

import pygame

from constants import (
    ASTEROID_MAX_RADIUS,
    BOSS_WAVE_INTERVAL,
    CLICK_DAMAGE_BASE,
    DIFFICULTY_SELECT_KEYS,
    FLOAT_COLOR,
    FLOAT_FONT_SIZE,
    FLOAT_LIFETIME_SECONDS,
    FLOAT_RISE_SPEED,
    HIT_STOP_BASE_S,
    HIT_STOP_MULTI_SCALE,
    HUD_CREDITS_ROW,
    HUD_LINE_STEP,
    HUD_MARGIN,
    IDLE_AUTOSAVE_SECONDS,
    MAX_DT,
    MILESTONE_CREDIT_BONUS,
    MILESTONE_SHIELD_CHARGES,
    MILESTONE_WAVE_INTERVAL,
    PALETTE,
    POWERUPS,
    POWERUP_ACTIVE_COLOR,
    SFX_CURSE,
    SFX_POWERUP,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    SCORE_COLOR,
    SCORE_POPUP_OFFSET_Y,
    SHAKE_BOMB,
    SHAKE_LARGE_ASTEROID,
    SHOP_BRIGHT_COLOR,
)
from achievements import Achievements, event_stats_from
from asteroid import Asteroid, Boss, boss_tier
from asteroidfield import AsteroidField
from blackhole import BlackHole, BlackHoleScheduler, spawn_position as hole_position
from comicfx import Burst, build_background_layers, burst_word, spawn_burst
from economy import Economy
from drones import DroneBay, OfflineBanner, drone_dps
from game import Game
from hud import (
    LowLivesWarning,
    WaveBanner,
    draw_boss_bar,
    draw_game_over,
    draw_help,
    draw_hud,
    draw_mode_menu,
    draw_pause,
    draw_run_summary,
    hud_font,
    points_for,
)
from logger import log_state, log_event
from particles import Particle, Shake, burst
from player import Player
from powerups import (
    CURSE_TYPES,
    PowerUp,
    PowerUpType,
    drops_powerup,
    drop_type,
    magnet_pull,
    mystery_pick_type,
    pick_type,
)
from saucer import (
    Saucer,
    SaucerScheduler,
    SaucerShot,
    spawn_side_position,
)
from shop import Shop
from stats import SOURCE_IDLE
import sound
from shot import Shot


def compute_dt(ms):
    """Clamped frame delta: a stall (alt-tab, window drag) must never move
    entities far enough to skip over a collision unchecked."""
    return min(ms / 1000, MAX_DT)


class HitStop:
    """Freeze-frame on kills (insanity core).

    `remaining` ticks on the real dt so a long request can never stall the
    loop forever; the sim's dt is gated to 0.0 while it runs —
    deterministic and testable through effective_frame_dt below.
    """

    def __init__(self):
        self.remaining = 0.0

    def freeze(self, scale=1.0):
        """Request a beat of base seconds × scale. The longest request wins:
        a later, shorter one may not shorten a freeze already running."""
        self.remaining = max(self.remaining, HIT_STOP_BASE_S * scale)

    def update(self, real_dt):
        self.remaining = max(0.0, self.remaining - real_dt)

    @property
    def frozen(self):
        return self.remaining > 0


def effective_frame_dt(dt, hit_stop):
    """Pure: the sim dt for a frame — 0.0 while a freeze holds, else real.

    Held by the gate: movement, drones, particles, timers, the banner, and
    the combo window. Ticking on real dt regardless: the freeze itself and
    the shake decay, so the pause always ends."""
    return 0.0 if hit_stop.frozen else dt


def freeze_for_destructions(hit_stop, count):
    """The beat a destruction wave buys: base for one kill in the frame,
    the multi beat for several, nothing for a cull or a whiff."""
    if hit_stop is None or count <= 0:
        return
    hit_stop.freeze(1.0 if count == 1 else HIT_STOP_MULTI_SCALE)


def try_dash(player, game):
    """SHIFT wiring (insanity core): dash the ship; a successful dash
    breaks the combo — the escape valve prices its i-frames. Returns
    whether the dash fired. The wiring lives in main, not on Player: the
    ship doesn't own run state."""
    if not player.dash():
        return False
    game.break_combo()
    return True


def handle_collisions(asteroids, shots, player1, game, powerups, shake=None,
                      hit_stop=None, saucers=None, enemy_shots=None):
    # The sweep reports hits to the Game instead of exiting the process
    # (engagement F2): a hit costs one of the lives, the ship respawns
    # invulnerable, and the run ends only at zero lives. Invulnerability is
    # checked before any hit is resolved, so a respawning ship can sit on
    # an asteroid for the grace window without losing another life. The
    # shield rides the same path inside Game.player_hit (F4).
    shot_kills = 0
    for asteroid in asteroids:
        if not asteroid.alive():
            continue
        if (
            game.state == "playing"
            and not player1.invulnerable
            and asteroid.collides_with(player1)
        ):
            log_event("player_hit")
            game.player_hit()
        for shot in shots:
            if not shot.alive():
                continue
            if asteroid.collides_with(shot):
                log_event("asteroid_shot")
                # Run stats (run-stats PR): a player shot connected — turret
                # shots ride the same pipeline tagged from_drone, and stay
                # out of the accuracy read. The kill also re-attributes the
                # rock below, so a chip history cannot turn a shot kill into
                # a click payout.
                if not shot.from_drone:
                    game.stats.record_hit()
                # V4: the word pops first, so it joins fx ahead of the
                # debris — the burst polygon sits behind the particle cloud
                # it salutes. POW! on large, BOOM! on medium, small stays
                # silent (burst_word is the pure gate).
                word = burst_word(asteroid.radius)
                if word is not None:
                    spawn_burst(asteroid.position, asteroid.radius, word)
                # F5: the parent bursts at its death site right before
                # splitting — any size; a large rock's destruction also
                # rocks the screen, mildly and scaled to its size. One
                # destruction path: this is where rocks die.
                burst(asteroid.position, asteroid.radius)
                sound.play_explosion(asteroid.radius)  # F6: pitched by size
                if asteroid.radius >= ASTEROID_MAX_RADIUS and shake is not None:
                    shake.kick(
                        SHAKE_LARGE_ASTEROID * asteroid.radius / ASTEROID_MAX_RADIUS
                    )
                asteroid.killed_by = SOURCE_IDLE  # run stats: the shot killed it
                # Every shot routes through the take_hit seam (the Boss
                # overrides it into its HP pool) — the sweep never calls
                # split() directly; plain rocks die exactly as before.
                destroyed = asteroid.take_hit()
                # Insanity chaos: PIERCE — the shot drills through plain
                # rocks and stays live for the next one. The boss's hull is
                # too thick to drill: a piercing shot dies on it like any
                # other, so a pass can't melt the whole pool per frame.
                drills_rocks = player1.has_pierce and not isinstance(asteroid, Boss)
                if not drills_rocks:
                    shot.kill()
                if destroyed:
                    # Insanity core: shot kills (player OR drone — drones fire
                    # real shots into this same group) advance the combo chain
                    # and pay points × its multiplier. Chip clicks and nukes
                    # never route here: credits-only, combo-free.
                    points = asteroid.kill_points
                    game.register_kill(points)
                    shot_kills += 1
                    # Distinct score popups: the points award floats as its own
                    # white '+N pts' at the kill site — display only, it touches
                    # neither the score nor the ledger. It starts a head above
                    # the credit float the destruction diff pays this same frame.
                    style = popup_style("points", points)
                    FloatingText(
                        asteroid.position.x,
                        asteroid.position.y - SCORE_POPUP_OFFSET_Y,
                        points,
                        label=style.label,
                        color=style.color,
                    )
                    # A destroyed non-small rock occasionally pays a pickup
                    # (F4); bosses never do (insanity threats) — and the
                    # guard reads before the roll, so a boss death draws no
                    # random number at all. drop_type (insanity chaos) rolls
                    # 40% of drops into the ? wildcard; its contents stay
                    # unknown until collected.
                    if not isinstance(asteroid, Boss) and drops_powerup(
                        asteroid.radius, random.random()
                    ):
                        kind = drop_type(random.random())
                        PowerUp(asteroid.position.x, asteroid.position.y, kind)
                        log_event("powerup_spawned", powerup_type=kind.value)
                break  # the hit is spent on this rock; skip its remaining shots

    # Insanity core: the frame's shot kills buy a freeze — one rock is a
    # base beat, several dying in one sweep is the multi beat.
    freeze_for_destructions(hit_stop, shot_kills)

    # Insanity threats: the four hostile branches, all guarded by the same
    # playing/invulnerable gates as the asteroid↔player branch above.
    if saucers is not None and enemy_shots is not None:
        # 1 · Enemy fire vs asteroids: real splits through take_hit — the
        # plain-rock path is the ordinary split (no combo, no points), the
        # boss soaks it as one HP like any shot. Destruction is destruction:
        # these kills buy hit-stop too.
        for shot in enemy_shots:
            if not shot.alive():
                continue
            for asteroid in asteroids:
                if not asteroid.alive() or not asteroid.collides_with(shot):
                    continue
                shot.kill()
                if asteroid.take_hit():
                    burst(asteroid.position, asteroid.radius)
                    sound.play_explosion(asteroid.radius)
                    shot_kills += 1
                break
        freeze_for_destructions(hit_stop, shot_kills)
        # 2 & 3 · Saucers and their fire vs the ship: a hit costs a life
        # through the standard player_hit path — shield absorbs, i-frames
        # (respawn or dash) protect.
        if game.state == "playing" and not player1.invulnerable:
            for saucer in saucers:
                if saucer.alive() and saucer.collides_with(player1):
                    log_event("player_hit")
                    game.player_hit()
                    break
            else:
                for shot in enemy_shots:
                    if shot.alive() and shot.collides_with(player1):
                        shot.kill()
                        log_event("player_hit")
                        game.player_hit()
                        break
        # 4 · Player fire vs saucers: the saucer soaks the shot; its death
        # pays SAUCER_KINDS[kind]["points"] through register_kill — a kill
        # exactly like any other, comboing and hit-stopping with the rest.
        for saucer in saucers:
            if not saucer.alive():
                continue
            for shot in shots:
                if not shot.alive() or not saucer.collides_with(shot):
                    continue
                shot.kill()
                burst(saucer.position, saucer.radius)
                if saucer.take_hit():
                    if shake is not None:
                        shake.kick(SHAKE_LARGE_ASTEROID)
                    log_event("saucer_defeated", kind=saucer.kind)
                    game.register_kill(saucer.points)
                    shot_kills += 1
                break
        freeze_for_destructions(hit_stop, shot_kills)

    # Pickups collect on player overlap — during play only, mirroring the
    # hit branch: a dead run grants nothing (F4).
    if game.state == "playing":
        for powerup in powerups:
            if not powerup.alive():
                continue
            if powerup.collides_with(player1):
                powerup.kill()
                kind = powerup.kind
                # Insanity chaos: a ? pickup's contents roll on collect —
                # the drop only ever promised a gamble.
                if kind is PowerUpType.MYSTERY:
                    log_event("mystery_collected")
                    kind = mystery_pick_type(random.random())
                if kind in CURSE_TYPES:
                    # The sting gets its own event and its own sound — the
                    # pickup jingle would be a lie about what just happened.
                    log_event("curse_revealed", curse=kind.value)
                    sound.play(SFX_CURSE)
                else:
                    log_event("powerup_collected", powerup_type=kind.value)
                    sound.play(sound.SFX_POWERUP)  # F6: the pickup jingle
                player1.activate_powerup(kind)


class MilestoneReward(NamedTuple):
    """What a milestone wave pays: shield charges stocked on the ship and a
    flat credit bonus to the idle ledger."""

    shield_charges: int
    credits: float


def milestone_reward(wave):
    """The grant for a wave number, or None when the wave pays none.

    Pure (Tier 1 milestone rewards): exactly the waves divisible by
    MILESTONE_WAVE_INTERVAL pay, so the trigger is provable without a
    live game.
    """
    if wave % MILESTONE_WAVE_INTERVAL != 0:
        return None
    return MilestoneReward(
        shield_charges=MILESTONE_SHIELD_CHARGES,
        credits=MILESTONE_CREDIT_BONUS,
    )


def maybe_advance_wave(game, field, banner, player=None, economy=None):
    """Start the next wave once the current one was populated and is cleared
    (engagement F3).

    The populated guard is the trap at both ends of a run: at game start and
    after R-restart the field is empty with wave at 1 — without it the
    counter would immediately tick to 2. Game over advances nothing.

    Tier 1 milestone rewards: every 5th wave stocks a shield charge on the
    ship and pays a flat credit bonus to the idle ledger, announced in the
    banner text. Player and economy ride optional kwargs — the
    handle_collisions precedent — so the pinned three-argument call shape
    (tests, the balance sim) keeps working unchanged.
    """
    if game.state != "playing":
        return
    if field.spawned_this_wave == 0 or len(game.asteroids) > 0:
        return
    game.wave += 1
    game.stats.record_wave_cleared()  # run stats: a wave survived (run-stats PR)
    field.start_wave()  # fresh spawn clock and populated guard for the new wave
    reward = milestone_reward(game.wave)
    if reward is not None:
        if player is not None:
            player.grant_shield(reward.shield_charges)
        if economy is not None:
            economy.grant_milestone(reward.credits)
    banner.show(
        game.wave,
        milestone_credits=None if reward is None else reward.credits,
    )
    sound.play(sound.SFX_WAVE_CLEAR)  # extra SFX: a rising arpeggio, wave won
    log_event("wave_started", wave=game.wave)
    if reward is not None:
        log_event(
            "milestone_reward",
            wave=game.wave,
            shield_charges=reward.shield_charges,
            credits=reward.credits,
        )


def magnet_pullables(powerups, floaters):
    """Every body the magnet can bend this frame: all drifting pickups plus
    the credit floats — the only floats flagged magnetic. Pure selection,
    so the pull's reach is pinned by tests.

    Points popups and shop/powerup notices hold their line: they are not
    things the ship collects, and dragging the shop's own labels around
    would read as a bug, not a feature.
    """
    pullables = list(powerups)
    pullables += [floater for floater in floaters or () if floater.magnetic]
    return pullables


def apply_magnet(game, player, dt, pullables):
    """The MAGNET drop's per-frame pass (Tier 3): while its clock runs on a
    live run, bend every nearby pullable's velocity toward the ship.

    Force, not teleport — magnet_pull accelerates each body (speed-capped,
    eased by distance) and the body's own update integrates the result; a
    body the magnet releases keeps the speed it gained. Playing-only: a
    dead run collects nothing, so it magnetizes nothing either.
    """
    if game.state != "playing" or not player.has_magnet:
        return
    for pullable in pullables:
        pullable.velocity = magnet_pull(
            pullable.position,
            player.position,
            pullable.velocity,
        )


def update_world(updatable, drones, asteroids, shots, player1, game, powerups,
                 shake, field, banner, economy, dt, warning=None,
                 hit_stop=None, saucers=None, enemy_shots=None,
                 blackholes=None, saucer_clock=None, hole_clock=None,
                 floaters=None):
    """One simulation step: every per-frame update, frozen whole while paused.

    The pause flag is the entire gate (Tier 1): a frozen frame ticks nothing
    — sprites, drone turrets, the collision sweep, the wave clock, the
    banner and shake, bought-powerup durations — so nothing ages, dies, or
    mints while the overlay is up. The boot menu (Tier 2 difficulty) freezes
    the same way: nothing has spawned yet, so the select screen sits over a
    still field. The event pump and the render stay live, so mute, resume,
    restart, and quit all still answer. main() also gates its
    destruction-diff poll and autosave on the same flag.

    Insanity core and threats (all keyword-optional, so the base flow works
    unchanged without them): the hit-stop freeze gates the sim's dt — the
    whole simulation holds (movement, drones, particles, timers, banner,
    combo window) while the freeze and the shake decay on real dt so the
    pause always ends; saucers update explicitly (their step needs the
    player and the enemy group, which the updatable pass doesn't forward);
    the threat clocks spawn saucers from wave 2 and black holes from wave 3
    — never during game over, and a hole never opens during a boss wave
    (the scheduler is told directly); and the combo window drains on sim
    time through game.tick.
    """
    if game.paused or game.state == "menu":
        return
    if hit_stop is not None:
        # Insanity core: the freeze-frame holds the whole simulation while
        # the freeze decays on real dt so it always ends.
        hit_stop.update(dt)
    sim_dt = effective_frame_dt(dt, hit_stop) if hit_stop is not None else dt
    if blackholes is not None:
        # Insanity threats: publish this frame's live wells before the world
        # update — every body's pull consult reads the registry this pass is
        # about to step. A well spawned later in the frame joins the next
        # frame's registry; one frame of latency, never a stale pull.
        blackhole.refresh_live_holes(blackholes)
    # Magnet (Tier 3): the pull bends velocities before this frame's
    # updates integrate them — accelerate, then move, the drift's own order.
    # On sim time: a frozen frame holds the pull like every other sim step.
    apply_magnet(game, player1, sim_dt, magnet_pullables(powerups, floaters))
    updatable.update(sim_dt)

    # Drone turrets fire real shots into the same pipeline (drones PR):
    # the sweep below and the destruction diff treat them exactly like
    # the player's own — one destruction path pays every source.
    drones.update(sim_dt, player1, asteroids, shots)

    # Saucers update explicitly, not through the group pass (insanity
    # threats): their step needs the player and the enemy group, which
    # the updatable pass doesn't forward.
    if saucers is not None:
        saucers.update(sim_dt, player1, enemy_shots)

    # Threat spawn clocks (insanity threats): saucers from wave 2, black
    # holes from wave 3 — never during game over, and a hole never opens
    # during a boss wave (the scheduler is told directly).
    if game.state == "playing" and saucer_clock is not None:
        kind = saucer_clock.update(sim_dt, game.wave)
        if kind is not None:
            Saucer(*spawn_side_position(kind), kind)
    if game.state == "playing" and hole_clock is not None:
        if hole_clock.update(sim_dt, game.wave,
                             game.wave % BOSS_WAVE_INTERVAL == 0):
            BlackHole(*hole_position())

    handle_collisions(asteroids, shots, player1, game, powerups, shake,
                      hit_stop=hit_stop, saucers=saucers,
                      enemy_shots=enemy_shots)
    maybe_advance_wave(game, field, banner, player1, economy)
    maybe_boss_wave(game, field)
    game.tick(sim_dt)  # insanity core: the combo window drains on sim time
    banner.update(sim_dt)
    shake.update(dt)  # F5: decay toward still before the frame is blitted

    # Low-lives warning (UX wave): the gate re-derives from lives + state
    # every frame — respawn, game over, and restart all leave it with no
    # dedicated hook, and a frozen run holds its phase with the rest.
    if warning is not None:
        warning.update(dt, game.lives, game.state)

    # Bought powerups tick on the dt-timer pattern: expire effects,
    # then publish the chrono scale the whole field reads this frame.
    economy.tick_powerups(sim_dt)
    Asteroid.speed_scale = economy.chrono_scale()
    # Insanity chaos: while the HOMING pickup runs, every friendly shot
    # steers — the speed_scale precedent: one class-level write per
    # frame, no per-shot wiring. None re-arms straight flight.
    Shot.homing_targets = asteroids if player1.has_homing else None


def maybe_boss_wave(game, field):
    """Spawn the wave-5 boss once its wave's field is empty (insanity threats).

    Guards: playing state, the wave multiple, and the field's populated
    guard — at spawn there must be no live rocks (the field spawns nothing
    on a boss wave anyway). The boss counts as the wave's population:
    bumping field.spawned_this_wave keeps maybe_advance_wave's cleared-field
    advance working unchanged after the boss dies. Runs right after the
    wave counter ticks, so a fresh boss wave arms the same frame.
    """
    if game.state != "playing" or game.wave % BOSS_WAVE_INTERVAL:
        return
    if field.spawned_this_wave > 0 or len(game.asteroids):
        return
    tier = boss_tier(game.wave)
    Boss(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2, tier)
    field.spawned_this_wave += 1
    log_event("boss_spawned", wave=game.wave, tier=tier)
    sound.play(sound.SFX_BOSS)


class _ClickPoint:
    """Zero-radius cursor probe so asteroid.collides_with works unchanged."""

    def __init__(self, pos):
        self.position = pygame.Vector2(pos)
        self.radius = 0.0


def asteroid_at(asteroids, pos):
    """The asteroid under the cursor, or None.

    Reuses the CircleShape collision test through a zero-radius probe; when
    several rocks overlap, the one nearest the click wins.
    """
    probe = _ClickPoint(pos)
    best = None
    best_dist = float("inf")
    for asteroid in asteroids:
        if not asteroid.collides_with(probe):
            continue
        dist = asteroid.position.distance_to(probe.position)
        if dist < best_dist:
            best, best_dist = asteroid, dist
    return best


def destroyed_asteroids(previous, current):
    """Asteroids that were on screen last frame and are gone now.

    The frame-to-frame group diff is the destruction detector: shots kill
    inside handle_collisions and clicks inside take_chip, but both funnel
    through kill() → group removal, so one poll sees every source without
    touching handle_collisions' pinned signature. split() children are new
    sprites absent from `previous`, so a split pays for the parent only.
    Asteroids flagged despawned (drifted off-screen, or the field cleared
    for a restart) are culls, not kills — they never mint.
    """
    return [
        asteroid
        for asteroid in previous
        if asteroid not in current and not asteroid.despawned
    ]


def nuke_field(asteroids):
    """The nuke: split the whole field to completion, right now.

    Every rock dies through the ordinary split() path — no free pass
    and no second mint path. The loop's destruction diff pays each
    rock that was on screen exactly once: split() children are new
    sprites absent from prev_asteroids, and children born and killed
    inside this same call never appear in any frame snapshot at all.
    Debris bursts fire here because the sweep's destruction site
    never sees these kills.
    """
    while len(asteroids) > 0:
        for rock in list(asteroids):
            burst(rock.position, rock.radius)
            # Run stats: the nuke killed these rocks, not any earlier chips
            # on them — re-attribute before the split pays the diff.
            rock.killed_by = SOURCE_IDLE
            rock.split()


def bomb_clear(hit_stop, shake, asteroids):
    """The bomb pickup's field clear (insanity chaos): the bought nuke's
    exact path — the whole field dies through the ordinary destruction
    diff (combo-free, credit-paying), the multi beat freezes the frame,
    and the screen rocks. Module-level so tests pin it without main()."""
    freeze_for_destructions(hit_stop, len(asteroids))
    nuke_field(asteroids)
    if shake is not None:
        shake.kick(SHAKE_BOMB)


def mint_destructions(previous, current, economy, stats, wave=None):
    """The idle mint poll: every wreck the frame diff finds pays the ledger
    exactly once — the one destruction→mint path (idle core).

    Returns (wreck, payout) pairs so the caller floats '+N' labels at the
    death sites. The run stats record here because the diff is the one
    place every destruction source surfaces (shots, clicks, drones, nukes):
    a rock lands in its size tier, and its payout in the click or idle
    bucket by the killer the wreck reports (run-stats PR).

    Bosses surface here but never mint (insanity threats): their death is
    score-only, paid through register_kill at the sweep — the diff pass
    logs the defeat and moves on.
    """
    paid = []
    for wreck in destroyed_asteroids(previous, current):
        if isinstance(wreck, Boss):
            log_event("boss_defeated", wave=wave)
            continue
        payout = economy.mint(wreck.radius)
        log_event("credit_minted", amount=payout)
        stats.record_destroyed(wreck.radius)
        stats.record_credits(payout, wreck.killed_by)
        paid.append((wreck, payout))
    return paid


def restart_run(game, economy, field, banner, asteroids, *, saucers=None,
                blackholes=None, enemy_shots=None, threat_clocks=()):
    """The R-key full restart — the game-over screen and the pause overlay
    both land here (F2, Tier 1), so this is the run-state reset's second
    hook beside Game.restart itself.

    A cleared field is not player destruction: every rock is flagged as a
    cull so the diff poll never mints for the restart. Game.restart resets
    the run — score, lives, wave, and the run stats in place — bought timed
    effects die with the run (the paid use is consumed), and the field
    forgets the old wave or its populated guard would see an empty fresh
    field and tick to wave 2 before anything spawns.

    Insanity threats: the hostiles and any live well clear with the run —
    each flagged a cull, never a paid kill, enemy fire swept with them —
    and the threat spawn clocks re-arm for the fresh run. All optional
    keywords: the base flow works unchanged without them.
    """
    for asteroid in asteroids:
        asteroid.despawned = True
    for group in (saucers, blackholes, enemy_shots):
        if group is None:
            continue
        for sprite in list(group):
            if hasattr(sprite, "despawned"):
                sprite.despawned = True
            sprite.kill()
    game.restart()
    economy.end_run_effects()
    field.start_wave()
    banner.show(game.wave)
    for clock in threat_clocks:
        clock.reset()


def select_mode(game, economy, field, banner, asteroids, mode):
    """The 1/2/3 difficulty select (Tier 2): persist the mode and launch
    the run — the boot menu's and the game-over screen's key handler,
    beside restart_run's R. Selection only happens outside a run, so
    restart() landing the mode's lives is the whole application."""
    game.set_mode(mode)
    restart_run(game, economy, field, banner, asteroids)


_float_font_cache = None


def float_font():
    """Lazily built small font for floating credit numbers."""
    global _float_font_cache
    if _float_font_cache is None:
        _float_font_cache = pygame.font.Font(None, FLOAT_FONT_SIZE)
    return _float_font_cache


def float_label(amount):
    """The '+N' string over a wreck; credits render as whole numbers."""
    return f"+{int(amount)}"


class PopupStyle(NamedTuple):
    """The resolved look of one floating-popup kind (distinct score popups).

    magnetic marks the kinds the MAGNET drop bends toward the ship — the
    credit float rides the pull, the points popup holds its line.
    """

    label: str
    color: tuple
    magnetic: bool = False


def popup_style(kind, amount):
    """Label + color + magnet flag for a floating popup, by kind.

    Pure (distinct score popups): both kinds share the FloatingText
    dt-timer template but never a look — points announce '+N pts' in the
    palette's warm white, credits keep their yellow '+N'. One resolver, so
    the two kinds cannot drift into each other.
    """
    if kind == "points":
        return PopupStyle(f"+{int(amount)} pts", SCORE_COLOR, magnetic=False)
    return PopupStyle(float_label(amount), FLOAT_COLOR, magnetic=True)


def click_damage(shop, economy):
    """Chip damage per click: the constant base scaled by Nanoblade
    levels — and ×10 while Overdrive runs (insane powerups). Shots
    never route here; they keep their instant-kill split()."""
    return CLICK_DAMAGE_BASE * shop.click_damage_mult() * economy.overdrive_mult()


class FloatingText(pygame.sprite.Sprite):
    """A small text line rising from a point and fading on the dt-timer.

    The idle core's '+N' credit float is the original; the distinct-score-
    popups wave made this the shared template — points and credits (and the
    shop/powerup notices) all ride it with their own resolved look. Lifetime
    runs on the dt-timer pattern — no wall-clock calls, so headless runs and
    tests step it deterministically.
    """

    containers = ()

    def __init__(self, x, y, amount, label=None, color=FLOAT_COLOR,
                 magnetic=False):
        if self.containers:
            super().__init__(self.containers)
        else:
            super().__init__()
        self.position = pygame.Vector2(x, y)
        # The resolved look rides the sprite so tests and evidence scripts
        # can tell which kind a float is without OCR-ing the surface.
        self.label = label or float_label(amount)
        self.color = color
        # The MAGNET drop bends only the floats flagged magnetic (the credit
        # kind): their pull rides this velocity, integrated with the rise.
        # Zero until a magnet grabs the float, so plain floats are unchanged.
        self.magnetic = magnetic
        self.velocity = pygame.Vector2(0, 0)
        self.surface = float_font().render(self.label, True, color)
        self.lifetime = FLOAT_LIFETIME_SECONDS

    def update(self, dt):
        self.lifetime -= dt
        self.position += self.velocity * dt
        self.position.y -= FLOAT_RISE_SPEED * dt
        if self.lifetime <= 0:
            self.kill()

    def draw(self, screen):
        screen.blit(self.surface, self.surface.get_rect(center=self.position))


def draw_credits(screen, credits):
    """Idle ledger readout under the insanity HUD slots — the economy's
    visible half. Row 5: below the combo (row 3) and dash (row 4) slots."""
    surface = hud_font().render(f"Credits: {int(credits)}", True, FLOAT_COLOR)
    screen.blit(surface, (HUD_MARGIN, HUD_MARGIN + HUD_CREDITS_ROW * HUD_LINE_STEP))


def render_world(screen, world, background, entities, fx, offset, game,
                 warning=None, dash_timer=None, player=None):
    """The V4 composition: three explicit passes into the world, then the
    screen-level steps — the blueprint's pass split, replacing the single
    flat drawable-group draw.

    Pass 1 paints the static action lines: the background pass, the only
    place background treatment may paint (entity draw functions never
    paint background, so their tests keep black-screen assertions). Pass 2
    draws the entities; pass 3 the fx — particles and burst texts, always
    above the field they decorate. The world blits at the shake offset
    (the draw origin moves, entity positions never do), the halftone
    dot-screen prints over it at screen level, and the HUD renders last,
    unshaken."""
    action_lines, halftone = background
    world.fill(PALETTE["paper"])
    world.blit(action_lines, (0, 0))  # pass 1: static action lines
    for each in entities:  # pass 2: player, rocks, shots, pickups
        each.draw(world)
    for each in fx:  # pass 3: particles + bursts, always atop entities
        each.draw(world)

    screen.fill(PALETTE["paper"])
    screen.blit(world, offset)
    screen.blit(halftone, (0, 0))  # the screen-level print, over the world
    # Low-lives warning (UX wave): the vignette prints above the halftone
    # but under the HUD text, so the pulsing line stays crisp while the
    # edges burn.
    if warning is not None:
        warning.draw_vignette(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             muted=game.muted,  # HUD last, above every world layer
             volume=getattr(game, "volume", None),
             lives_pulse=warning.pulse if warning is not None else None,
             combo=game.combo, dash_timer=dash_timer,
             magnet=player.magnet_timer if player is not None else None)


def main():
    pygame.init()
    sound.init()  # F6: mixer + SFX; any failure degrades to a silent no-op
    game_clk = pygame.time.Clock()
    dt = 0
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    updatable = pygame.sprite.Group()
    # V4: the flat drawable group splits into explicit passes — entities
    # (player, rocks, shots, pickups) and fx (particles, bursts, floaters)
    # — so fx always renders above the field it decorates, no matter the
    # order things spawned in.
    entities = pygame.sprite.Group()
    fx = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    floaters = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()
    # Insanity threats: enemy fire and world hazards get their own groups —
    # `shots` stays the player-and-drone group, so every existing
    # combo/score branch keeps reading only friendly fire.
    enemy_shots = pygame.sprite.Group()
    saucers = pygame.sprite.Group()
    blackholes = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, entities)
    Shot.containers = (shots, updatable, entities)
    PowerUp.containers = (powerups, updatable, entities)
    Particle.containers = (particles, updatable, fx)
    AsteroidField.containers = updatable
    FloatingText.containers = (floaters, updatable, fx)
    Burst.containers = (fx, updatable)
    SaucerShot.containers = (enemy_shots, updatable, entities)
    # Saucers are NOT in updatable: their step needs the player and the
    # enemy-shot group, which the plain group pass doesn't forward —
    # update_world steps them explicitly instead.
    Saucer.containers = (saucers, entities)
    BlackHole.containers = (blackholes, updatable, entities)

    Player.containers = (updatable, entities)
    player1 = Player(SCREEN_WIDTH/2, SCREEN_HEIGHT/2 )
    # F5: the shake lives in main (it offsets the render, not the world);
    # Game and the sweep get it so they can kick it where lives are lost
    # and rocks die.
    shake = Shake()
    # Insanity core: the hit-stop freeze lives in main for the same reason —
    # it gates the sim dt, not the world.
    hit_stop = HitStop()
    # Insanity threats: the saucer and black-hole spawn clocks live in main
    # (they schedule world events; they are not run state).
    saucer_clock = SaucerScheduler()
    hole_clock = BlackHoleScheduler()
    # Bomb pickup (insanity chaos): the ship never owns the world, so the
    # field-clear callback is injected here — the bought nuke's exact path.
    player1.bomb_field = lambda: bomb_clear(hit_stop, shake, asteroids)
    game = Game(player1, asteroids, shots, powerups, particles=particles, shake=shake)
    # F6: start from the persisted mute preference — the sound module only
    # learns it here; playback stays suppressed either way.
    sound.set_muted(game.muted)
    # Master volume: same seam, one sync — the persisted level scales every
    # SFX from the first frame.
    sound.set_volume(game.volume)

    # The field reads the wave off the Game (F3), so it is built after one
    # exists. No boot banner flash — Tier 2's menu owns the first screen,
    # and restart_run arms the WAVE 1 flash when a mode launches the run.
    asteroid_field = AsteroidField(game)
    banner = WaveBanner()
    # Low-lives warning (UX wave): pulses the HUD lives line and prints the
    # edge vignette while exactly one life remains. Not run state — it
    # re-derives its gate from the Game every frame.
    warning = LowLivesWarning()

    economy = Economy()
    shop = Shop(economy, player1)  # applies any save-loaded effect levels
    drones = DroneBay(economy)  # turret count follows the Drones level
    # One-time boot grant (drones PR): time away pays through the capped
    # offline math, priced off the saved Drones level. A missing
    # idle_last_seen (fresh install, pre-drones save) grants nothing.
    offline_banner = OfflineBanner(
        economy.claim_offline(drone_dps(economy.levels["drone"]))
    )
    if offline_banner.amount > 0:
        log_event("offline_earnings", amount=offline_banner.amount)

    # Tier 2 difficulty modes: boot into the select menu; 1/2/3 launch the
    # run through select_mode → restart_run. The Game itself still
    # constructs in "playing" — the balance sim and the tests drive runs
    # directly — the menu is main()'s flow, not the Game's default.
    game.state = "menu"

    # Achievements (Tier 2): the unlocked set loads from the shared save's
    # merge; evaluation below is pure and idempotent, so it can run every
    # unpaused frame.
    achievements = Achievements()
    prev_asteroids = set(asteroids)
    autosave_timer = 0.0

    # F5: the world renders to its own surface so the shake can offset the
    # blit origin — entity draw calls and positions never change. Built once.
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))

    # V3/V4: the comic background pre-renders once as a pair — the action
    # lines layer (blitted into the world as the background pass, under the
    # entities) and the halftone dot-screen (the screen-level print over the
    # shaken world). Entity draw functions never paint background; all
    # background treatment lives in this composition.
    background = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)


    while True:
        log_state()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                economy.save()
                pygame.quit()
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                # F6: mute is playback-only, works in any state, and persists
                # through the save loader. Kept in this event-pump block;
                # later features add their input alongside it.
                sound.set_muted(game.toggle_mute())
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
                # Master volume (UX wave): [ steps down, ] steps up, 10%
                # per press in any state, persisted through the save
                # loader. Mute still overrides audibly and never touches
                # the level — same seam as the M branch above.
                direction = 1 if event.key == pygame.K_RIGHTBRACKET else -1
                sound.set_volume(game.step_volume(direction))
            if (event.type == pygame.KEYDOWN
                    and event.key in (pygame.K_p, pygame.K_ESCAPE)):
                # Tier 1 pause: P or Esc freezes a live run and shows the
                # overlay. Game over owns its own screen — toggle_pause
                # refuses there — and mute above stays live while frozen.
                game.toggle_pause()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_h:
                # Tier 1 help: H toggles the keybind list over dimmed play.
                # Documentation, not a world change — it dims but never
                # freezes, so it answers while frozen too (the pause keys
                # above stay live with the list up). Game over keeps its
                # own screen; toggle_help refuses there, same as pause.
                game.toggle_help()
            if event.type == pygame.KEYDOWN and (
                    game.state == "game_over" or game.paused):
                # R restarts, Q quits (engagement F2). The pause overlay
                # promises the same two keys while frozen (Tier 1 pause):
                # restart unpauses through Game.restart, and quit saves
                # exactly like the game-over path.
                if event.key == pygame.K_r:
                    restart_run(game, economy, asteroid_field, banner,
                                asteroids, saucers=saucers,
                                blackholes=blackholes,
                                enemy_shots=enemy_shots,
                                threat_clocks=(saucer_clock, hole_clock))
                elif event.key == pygame.K_q:
                    economy.save()
                    pygame.quit()
                    return
            if event.type == pygame.KEYDOWN and game.state in ("menu", "game_over"):
                # Tier 2 difficulty modes: 1/2/3 pick the next run's mode
                # and launch it — the start/game-over flow's select, beside
                # F2's R/Q above (R restarts the current mode). Q also quits
                # from the menu, so the boot screen is never a trap.
                mode = DIFFICULTY_SELECT_KEYS.get(event.key)
                if mode is not None:
                    select_mode(
                        game, economy, asteroid_field, banner, asteroids, mode
                    )
                elif event.key == pygame.K_q and game.state == "menu":
                    economy.save()
                    pygame.quit()
                    return
            if (event.type == pygame.KEYDOWN and not game.paused
                    and game.state == "playing"):
                # Shop keys 1–4 (idle shop): additive beside F2's R/Q —
                # different keys, so neither branch shadows the other.
                # A frozen run answers nothing but the overlay keys (and M
                # above): ledger spends and nukes must not fire mid-pause.
                # Tier 2: playing-only, because 1/2/3 mean difficulty select
                # on the menu and game-over screens — the shop can no longer
                # answer there and shadow the select.
                purchase = shop.handle_key(event.key)
                if purchase is not None:
                    x, y = shop.cell_center(purchase.name)
                    FloatingText(
                        x,
                        y,
                        0,
                        label=f"{purchase.title} Lv {purchase.level}",
                        color=SHOP_BRIGHT_COLOR,
                    )
                # Bought powerups (insane-powerups): keys 7–0 activate
                # only when the ledger can pay the escalating price. The
                # nuke is the one activation that also destroys — through
                # the normal splits, so the destruction diff mints each
                # rock exactly once.
                powerup = shop.handle_powerup_key(event.key)
                if powerup is not None:
                    if powerup == "nuke":
                        # The whole field dying in one call is the multi
                        # beat (a lone rock's nuke is a base beat) — credits
                        # still mint through the diff, combo-free.
                        freeze_for_destructions(hit_stop, len(asteroids))
                        nuke_field(asteroids)
                    sound.play(SFX_POWERUP)
                    log_event("powerup_activated", name=powerup)
                    FloatingText(
                        SCREEN_WIDTH / 2,
                        SCREEN_HEIGHT / 3,
                        0,
                        label=f"{POWERUPS[powerup]['title'].upper()}!",
                        color=POWERUP_ACTIVE_COLOR,
                    )
            if event.type == pygame.MOUSEBUTTONDOWN and not game.paused:
                # Idle core: a click chips the rock under the cursor. take_chip
                # routes any kill through split(), so every destruction source
                # shares one downstream mint path (the group diff below).
                # Paused frames chip nothing — world mutations hold.
                target = asteroid_at(asteroids, event.pos)
                if target is not None:
                    # A click kill is still a destruction: one base beat,
                    # combo-free (take_chip never routes to register_kill).
                    destroyed = target.take_chip(click_damage(shop, economy))
                    freeze_for_destructions(hit_stop, 1 if destroyed else 0)
            if (
                event.type == pygame.KEYDOWN
                and event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT)
                and game.state == "playing"
            ):
                # Dash (insanity core): L/R-SHIFT keydown dashes along the
                # nose. Gated to play so a SHIFT press on the game-over
                # screen can't spend the cooldown.
                try_dash(player1, game)

        ms = game_clk.tick(60)
        dt = compute_dt(ms)
        # Ambient music (Tier 3): the loop follows the run — audible during
        # gameplay (a paused run is still live), silent on the menu and the
        # game-over screen. Mute and the master level reach it through the
        # same seams as the SFX; this call only carries the boundary.
        sound.update_music(game.state == "playing")
        update_world(updatable, drones, asteroids, shots, player1, game,
                     powerups, shake, asteroid_field, banner, economy, dt,
                     warning, floaters=floaters,
                     hit_stop=hit_stop, saucers=saucers,
                     enemy_shots=enemy_shots, blackholes=blackholes,
                     saucer_clock=saucer_clock, hole_clock=hole_clock)

        if not game.paused:
            # Destruction → credits: diff this frame's field against the
            # last, mint once per wreck, float a '+N' over the wreck.
            # Frozen frames change no groups, so the poll holds too. The
            # run stats record inside the same poll (run-stats PR). Bosses
            # route through the same diff but mint nothing — their death
            # is score-only, logged where the paid kill is known.
            for wreck, payout in mint_destructions(
                    prev_asteroids, asteroids, economy, game.stats,
                    wave=game.wave):
                style = popup_style("credits", payout)
                FloatingText(
                    wreck.position.x,
                    wreck.position.y,
                    payout,
                    label=style.label,
                    color=style.color,
                    magnetic=style.magnetic,
                )
            prev_asteroids = set(asteroids)

            # Achievements (Tier 2): a pure per-frame evaluation over the
            # run and lifetime counters — idempotent once everything is
            # unlocked. New awards persist through the save merge and queue
            # toasts. Frozen frames evaluate nothing, like the mint poll.
            achievements.evaluate(event_stats_from(game, economy))
            achievements.update(dt)

            autosave_timer += dt
            if autosave_timer >= IDLE_AUTOSAVE_SECONDS:
                autosave_timer = 0.0
                economy.save()

        # V4: three explicit passes into the world, then the screen-level
        # steps — the world blit at the shaken offset (the draw origin
        # moves, entities don't), the halftone print, HUD last and unshaken
        # so the score stays readable while the world rocks (F5).
        render_world(screen, world, background, entities, fx, shake.offset(),
                     game, warning, player=player1,
                     dash_timer=player1.dash_timer
                     if game.state == "playing" else None)
        draw_credits(screen, economy.credits)
        # The boss HP bar sits top-center during a boss fight (insanity
        # threats) — under the HUD rows, over the world.
        if game.state == "playing":
            live_boss = next(
                (rock for rock in asteroids if isinstance(rock, Boss)), None
            )
            if live_boss is not None:
                draw_boss_bar(screen, live_boss)
        if not game.paused:
            offline_banner.update(dt)  # a frozen frame fades no UI timers
        offline_banner.draw(screen)
        drones.draw(screen, player1)
        shop.draw_panel(screen)
        shop.draw_powerups(screen)
        achievements.draw(screen)  # the top-center toast seat, under overlays
        if game.state == "menu":
            # Tier 2: the difficulty select over the still, empty field.
            draw_mode_menu(screen, game.mode, game.high_scores)
        elif game.state == "game_over":
            draw_game_over(screen, game.score, new_high=game.new_high,
                           mode=game.mode, top_chain=game.combo.top,
                           best_multiplier=game.combo.best_multiplier)
            # Run stats (run-stats PR): the run's counters, in a summary
            # block under the game-over prompt.
            draw_run_summary(screen, game.stats)
        elif game.paused:
            draw_pause(screen)  # the frozen world dims under the prompt
        if game.help_open:
            draw_help(screen)  # over dimmed play — or over the paused dim
        banner.draw(screen)  # on top: the WAVE n flash overlays everything

        pygame.display.flip()
        


if __name__ == "__main__":
    main()
