import random

import pygame

from constants import (
    ASTEROID_MAX_RADIUS,
    BOSS_WAVE_INTERVAL,
    CLICK_DAMAGE_BASE,
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
    PALETTE,
    POWERUPS,
    POWERUP_ACTIVE_COLOR,
    SFX_CURSE,
    SFX_POWERUP,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    SHAKE_BOMB,
    SHAKE_LARGE_ASTEROID,
    SHOP_BRIGHT_COLOR,
)
from asteroid import Asteroid, Boss, boss_tier
from asteroidfield import AsteroidField
from blackhole import BlackHole, BlackHoleScheduler, spawn_position as hole_position
from economy import Economy
from drones import DroneBay, OfflineBanner, drone_dps
from game import Game
from hud import (
    WaveBanner,
    draw_boss_bar,
    draw_game_over,
    draw_hud,
    hud_font,
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
    mystery_pick_type,
)
from saucer import (
    Saucer,
    SaucerScheduler,
    SaucerShot,
    spawn_side_position,
)
from shop import Shop
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
                    game.register_kill(asteroid.kill_points)
                    shot_kills += 1
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


def maybe_advance_wave(game, field, banner):
    """Start the next wave once the current one was populated and is cleared
    (engagement F3).

    The populated guard is the trap at both ends of a run: at game start and
    after R-restart the field is empty with wave at 1 — without it the
    counter would immediately tick to 2. Game over advances nothing.
    """
    if game.state != "playing":
        return
    if field.spawned_this_wave == 0 or len(game.asteroids) > 0:
        return
    game.wave += 1
    field.start_wave()  # fresh spawn clock and populated guard for the new wave
    banner.show(game.wave)
    log_event("wave_started", wave=game.wave)


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


def click_damage(shop, economy):
    """Chip damage per click: the constant base scaled by Nanoblade
    levels — and ×10 while Overdrive runs (insane powerups). Shots
    never route here; they keep their instant-kill split()."""
    return CLICK_DAMAGE_BASE * shop.click_damage_mult() * economy.overdrive_mult()


class FloatingText(pygame.sprite.Sprite):
    """A '+N' credit number rising from a fresh wreck (idle core).

    Lifetime runs on the dt-timer pattern — no wall-clock calls, so
    headless runs and tests step it deterministically.
    """

    containers = ()

    def __init__(self, x, y, amount, label=None, color=FLOAT_COLOR):
        if self.containers:
            super().__init__(self.containers)
        else:
            super().__init__()
        self.position = pygame.Vector2(x, y)
        self.surface = float_font().render(label or float_label(amount), True, color)
        self.lifetime = FLOAT_LIFETIME_SECONDS

    def update(self, dt):
        self.lifetime -= dt
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


def main():
    pygame.init()
    sound.init()  # F6: mixer + SFX; any failure degrades to a silent no-op
    game_clk = pygame.time.Clock()
    dt = 0
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
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

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)
    AsteroidField.containers = updatable
    FloatingText.containers = (floaters, updatable, drawable)
    SaucerShot.containers = (enemy_shots, updatable, drawable)
    Saucer.containers = (saucers, drawable)
    BlackHole.containers = (blackholes, updatable, drawable)

    Player.containers = (updatable, drawable)
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

    # The field reads the wave off the Game (F3), so it is built after one
    # exists. The WAVE 1 flash arms at game start.
    asteroid_field = AsteroidField(game)
    banner = WaveBanner()
    banner.show(game.wave)

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

    prev_asteroids = set(asteroids)
    autosave_timer = 0.0

    # F5: the world renders to its own surface so the shake can offset the
    # blit origin — entity draw calls and positions never change. Built once.
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))

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
            if event.type == pygame.KEYDOWN and game.state == "game_over":
                # R restarts, Q quits (engagement F2). Kept in this event-pump
                # block; later features add their input alongside it.
                if event.key == pygame.K_r:
                    # A cleared field is not player destruction: flag every
                    # rock as a cull so the diff poll never mints for restart.
                    for asteroid in asteroids:
                        asteroid.despawned = True
                    # Insanity threats: restart clears the hostiles and any
                    # live well too — each a cull, never a paid kill.
                    for saucer in saucers:
                        saucer.despawned = True
                        saucer.kill()
                    for hole in blackholes:
                        hole.despawned = True
                        hole.kill()
                    for shot in list(enemy_shots):
                        shot.kill()
                    game.restart()
                    # Bought timed effects die with the run: the paid
                    # use is consumed, the new run starts clean.
                    economy.end_run_effects()
                    # The field forgets the old wave too, or its populated
                    # guard would see an empty field and tick to wave 2
                    # before the fresh run spawns anything.
                    asteroid_field.start_wave()
                    banner.show(game.wave)
                    # The threat clocks re-arm with the run (insanity threats).
                    saucer_clock.reset()
                    hole_clock.reset()
                elif event.key == pygame.K_q:
                    economy.save()
                    pygame.quit()
                    return
            if event.type == pygame.KEYDOWN:
                # Shop keys 1–4 (idle shop): additive beside F2's R/Q —
                # different keys, so neither branch shadows the other.
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
            if event.type == pygame.MOUSEBUTTONDOWN:
                # Idle core: a click chips the rock under the cursor. take_chip
                # routes any kill through split(), so every destruction source
                # shares one downstream mint path (the group diff below).
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
        # Insanity core: the freeze-frame holds the whole simulation —
        # movement, drones, particles, timers, banner, combo window — while
        # the freeze and the shake decay on real dt so the pause always ends.
        hit_stop.update(dt)
        sim_dt = effective_frame_dt(dt, hit_stop)
        updatable.update(sim_dt)
        # player1.update(dt)

        # Drone turrets fire real shots into the same pipeline (drones PR):
        # the sweep below and the destruction diff treat them exactly like
        # the player's own — one destruction path pays every source.
        drones.update(sim_dt, player1, asteroids, shots)

        # Saucers update explicitly, not through the group pass (insanity
        # threats): their step needs the player and the enemy group, which
        # the updatable pass doesn't forward.
        saucers.update(sim_dt, player1, enemy_shots)

        # Threat spawn clocks (insanity threats): saucers from wave 2, black
        # holes from wave 3 — never during game over, and a hole never opens
        # during a boss wave (the scheduler is told directly).
        if game.state == "playing":
            kind = saucer_clock.update(sim_dt, game.wave)
            if kind is not None:
                Saucer(*spawn_side_position(kind), kind)
            if hole_clock.update(sim_dt, game.wave,
                                 game.wave % BOSS_WAVE_INTERVAL == 0):
                BlackHole(*hole_position())

        handle_collisions(asteroids, shots, player1, game, powerups, shake,
                          hit_stop=hit_stop, saucers=saucers,
                          enemy_shots=enemy_shots)
        maybe_advance_wave(game, asteroid_field, banner)
        maybe_boss_wave(game, asteroid_field)
        game.tick(sim_dt)  # insanity core: the combo window drains on sim time
        banner.update(sim_dt)
        shake.update(dt)  # F5: decay toward still before the frame is blitted

        # Bought powerups tick on the dt-timer pattern: expire effects,
        # then publish the chrono scale the whole field reads this frame.
        economy.tick_powerups(sim_dt)
        Asteroid.speed_scale = economy.chrono_scale()
        # Insanity chaos: while the HOMING pickup runs, every friendly shot
        # steers — the speed_scale precedent: one class-level write per
        # frame, no per-shot wiring. None re-arms straight flight.
        Shot.homing_targets = asteroids if player1.has_homing else None

        # Destruction → credits: diff this frame's field against the last,
        # mint once per wreck, float a '+N' over the wreck. Bosses route
        # through the same diff but mint nothing (mintable=False) — their
        # death is score-only, logged here where the paid kill is known.
        for wreck in destroyed_asteroids(prev_asteroids, asteroids):
            if isinstance(wreck, Boss):
                log_event("boss_defeated", wave=game.wave)
                continue
            payout = economy.mint(wreck.radius)
            log_event("credit_minted", amount=payout)
            FloatingText(wreck.position.x, wreck.position.y, payout)
        prev_asteroids = set(asteroids)

        autosave_timer += dt
        if autosave_timer >= IDLE_AUTOSAVE_SECONDS:
            autosave_timer = 0.0
            economy.save()

        world.fill(PALETTE["paper"])
        for each in drawable:
            each.draw(world)

        # The world is blitted at the shaken offset — the draw origin moves,
        # entities don't. HUD and banners draw after, unshaken, so the
        # score stays readable while the world rocks (F5).
        screen.fill(PALETTE["paper"])
        screen.blit(world, shake.offset())

        draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
                 muted=game.muted, combo=game.combo,
                 dash_timer=player1.dash_timer if game.state == "playing" else None)
        draw_credits(screen, economy.credits)
        # The boss HP bar sits top-center during a boss fight (insanity
        # threats) — under the HUD rows, over the world.
        if game.state == "playing":
            live_boss = next(
                (rock for rock in asteroids if isinstance(rock, Boss)), None
            )
            if live_boss is not None:
                draw_boss_bar(screen, live_boss)
        offline_banner.update(dt)
        offline_banner.draw(screen)
        drones.draw(screen, player1)
        shop.draw_panel(screen)
        shop.draw_powerups(screen)
        if game.state == "game_over":
            draw_game_over(screen, game.score, new_high=game.new_high,
                           top_chain=game.combo.top,
                           best_multiplier=game.combo.best_multiplier)
        banner.draw(screen)  # on top: the WAVE n flash overlays everything

        pygame.display.flip()
        


if __name__ == "__main__":
    main()
