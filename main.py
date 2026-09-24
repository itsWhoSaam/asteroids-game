import random

import pygame

from constants import MAX_DT, SCREEN_WIDTH, SCREEN_HEIGHT
from asteroid import Asteroid
from asteroidfield import AsteroidField
from game import Game
from logger import log_state, log_event
from player import Player
from hud import WaveBanner, draw_game_over, draw_hud, points_for
from powerups import PowerUp, drops_powerup, pick_type
from shot import Shot


def compute_dt(ms):
    """Clamped frame delta: a stall (alt-tab, window drag) must never move
    entities far enough to skip over a collision unchecked."""
    return min(ms / 1000, MAX_DT)


def handle_collisions(asteroids, shots, player1, game, powerups):
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


def main():
    pygame.init()
    game_clk = pygame.time.Clock()
    dt = 0
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    AsteroidField.containers = updatable

    Player.containers = (updatable, drawable)
    player1 = Player(SCREEN_WIDTH/2, SCREEN_HEIGHT/2 )
    game = Game(player1, asteroids, shots, powerups)

    # The field reads the wave off the Game (F3), so it is built after one
    # exists. The WAVE 1 flash arms at game start.
    asteroid_field = AsteroidField(game)
    banner = WaveBanner()
    banner.show(game.wave)

    while True:
        log_state()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type == pygame.KEYDOWN and game.state == "game_over":
                # R restarts, Q quits (engagement F2). Kept in this event-pump
                # block; later features add their input alongside it.
                if event.key == pygame.K_r:
                    game.restart()
                    # The field forgets the old wave too, or its populated
                    # guard would see an empty field and tick to wave 2
                    # before the fresh run spawns anything.
                    asteroid_field.start_wave()
                    banner.show(game.wave)
                elif event.key == pygame.K_q:
                    pygame.quit()
                    return

        ms = game_clk.tick(60)
        dt = compute_dt(ms)
        updatable.update(dt)
        # player1.update(dt)

        handle_collisions(asteroids, shots, player1, game, powerups)
        maybe_advance_wave(game, asteroid_field, banner)
        banner.update(dt)

        screen.fill("black")

        for each in drawable:
            each.draw(screen)
        # player1.draw(screen)

        draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
        if game.state == "game_over":
            draw_game_over(screen, game.score, new_high=game.new_high)
        banner.draw(screen)  # on top: the WAVE n flash overlays everything

        pygame.display.flip()
        


if __name__ == "__main__":
    main()
