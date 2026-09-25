import random

import pygame

from constants import (
    ASTEROID_MAX_RADIUS,
    CLICK_DAMAGE_BASE,
    FLOAT_COLOR,
    FLOAT_FONT_SIZE,
    FLOAT_LIFETIME_SECONDS,
    FLOAT_RISE_SPEED,
    HUD_LINE_STEP,
    HUD_MARGIN,
    IDLE_AUTOSAVE_SECONDS,
    MAX_DT,
    PALETTE,
    POWERUPS,
    POWERUP_ACTIVE_COLOR,
    SFX_POWERUP,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    SHAKE_LARGE_ASTEROID,
    SHOP_BRIGHT_COLOR,
)
from asteroid import Asteroid
from asteroidfield import AsteroidField
from comicfx import build_background
from economy import Economy
from drones import DroneBay, OfflineBanner, drone_dps
from game import Game
from hud import WaveBanner, draw_game_over, draw_hud, hud_font, points_for
from logger import log_state, log_event
from particles import Particle, Shake, burst
from player import Player
from powerups import PowerUp, drops_powerup, pick_type
from shop import Shop
import sound
from shot import Shot


def compute_dt(ms):
    """Clamped frame delta: a stall (alt-tab, window drag) must never move
    entities far enough to skip over a collision unchecked."""
    return min(ms / 1000, MAX_DT)


def handle_collisions(asteroids, shots, player1, game, powerups, shake=None):
    # The sweep reports hits to the Game instead of exiting the process
    # (engagement F2): a hit costs one of the lives, the ship respawns
    # invulnerable, and the run ends only at zero lives. Invulnerability is
    # checked before any hit is resolved, so a respawning ship can sit on
    # an asteroid for the grace window without losing another life. The
    # shield rides the same path inside Game.player_hit (F4).
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
                asteroid.split()
                shot.kill()
                game.add_score(points_for(asteroid.radius))
                # A destroyed non-small rock occasionally pays a pickup (F4).
                # The pure rolls keep the decision testable; the new PowerUp
                # joins its containers like every other sprite.
                if drops_powerup(asteroid.radius, random.random()):
                    kind = pick_type(random.random())
                    PowerUp(asteroid.position.x, asteroid.position.y, kind)
                    log_event("powerup_spawned", powerup_type=kind.value)
                break  # the hit killed the asteroid; skip its remaining shots

    # Pickups collect on player overlap — during play only, mirroring the
    # hit branch: a dead run grants nothing (F4).
    if game.state == "playing":
        for powerup in powerups:
            if not powerup.alive():
                continue
            if powerup.collides_with(player1):
                powerup.kill()
                player1.activate_powerup(powerup.kind)
                log_event("powerup_collected", powerup_type=powerup.kind.value)
                sound.play(sound.SFX_POWERUP)  # F6: the pickup jingle


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
    """Idle ledger readout under the score HUD — the economy's visible half."""
    surface = hud_font().render(f"Credits: {int(credits)}", True, FLOAT_COLOR)
    screen.blit(surface, (HUD_MARGIN, HUD_MARGIN + 3 * HUD_LINE_STEP))


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

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)
    AsteroidField.containers = updatable
    FloatingText.containers = (floaters, updatable, drawable)

    Player.containers = (updatable, drawable)
    player1 = Player(SCREEN_WIDTH/2, SCREEN_HEIGHT/2 )
    # F5: the shake lives in main (it offsets the render, not the world);
    # Game and the sweep get it so they can kick it where lives are lost
    # and rocks die.
    shake = Shake()
    game = Game(player1, asteroids, shots, powerups, particles=particles, shake=shake)
    # F6: start from the persisted mute preference — the sound module only
    # learns it here; playback stays suppressed either way.
    sound.set_muted(game.muted)
    # Master volume: same seam, one sync — the persisted level scales every
    # SFX from the first frame.
    sound.set_volume(game.volume)

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

    # V3: the comic background pre-renders once alongside it — halftone
    # dot-screen and radial action lines over the paper — and blits every
    # frame as a screen-level print texture. Entity draw functions never
    # paint background; all background treatment lives in this composition.
    background = build_background(SCREEN_WIDTH, SCREEN_HEIGHT)

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
            if event.type == pygame.KEYDOWN and game.state == "game_over":
                # R restarts, Q quits (engagement F2). Kept in this event-pump
                # block; later features add their input alongside it.
                if event.key == pygame.K_r:
                    # A cleared field is not player destruction: flag every
                    # rock as a cull so the diff poll never mints for restart.
                    for asteroid in asteroids:
                        asteroid.despawned = True
                    game.restart()
                    # Bought timed effects die with the run: the paid
                    # use is consumed, the new run starts clean.
                    economy.end_run_effects()
                    # The field forgets the old wave too, or its populated
                    # guard would see an empty field and tick to wave 2
                    # before the fresh run spawns anything.
                    asteroid_field.start_wave()
                    banner.show(game.wave)
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
                    target.take_chip(click_damage(shop, economy))

        ms = game_clk.tick(60)
        dt = compute_dt(ms)
        updatable.update(dt)
        # player1.update(dt)

        # Drone turrets fire real shots into the same pipeline (drones PR):
        # the sweep below and the destruction diff treat them exactly like
        # the player's own — one destruction path pays every source.
        drones.update(dt, player1, asteroids, shots)

        handle_collisions(asteroids, shots, player1, game, powerups, shake)
        maybe_advance_wave(game, asteroid_field, banner)
        banner.update(dt)
        shake.update(dt)  # F5: decay toward still before the frame is blitted

        # Bought powerups tick on the dt-timer pattern: expire effects,
        # then publish the chrono scale the whole field reads this frame.
        economy.tick_powerups(dt)
        Asteroid.speed_scale = economy.chrono_scale()

        # Destruction → credits: diff this frame's field against the last,
        # mint once per wreck, float a '+N' over the wreck.
        for wreck in destroyed_asteroids(prev_asteroids, asteroids):
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
        # V3: the print texture sits over the shaken world and under the HUD
        # — screen-level, so it never scrolls or shakes with the world.
        screen.blit(background, (0, 0))

        draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
                 muted=game.muted, volume=game.volume)
        draw_credits(screen, economy.credits)
        offline_banner.update(dt)
        offline_banner.draw(screen)
        drones.draw(screen, player1)
        shop.draw_panel(screen)
        shop.draw_powerups(screen)
        if game.state == "game_over":
            draw_game_over(screen, game.score, new_high=game.new_high)
        banner.draw(screen)  # on top: the WAVE n flash overlays everything

        pygame.display.flip()
        


if __name__ == "__main__":
    main()
