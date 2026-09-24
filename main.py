import pygame

from constants import MAX_DT, SCREEN_WIDTH, SCREEN_HEIGHT
from asteroid import Asteroid
from asteroidfield import AsteroidField
from game import Game
from logger import log_state, log_event
from player import Player
from hud import draw_hud, draw_game_over, points_for
from shot import Shot


def compute_dt(ms):
    """Clamped frame delta: a stall (alt-tab, window drag) must never move
    entities far enough to skip over a collision unchecked."""
    return min(ms / 1000, MAX_DT)


def handle_collisions(asteroids, shots, player1, game):
    # The sweep reports hits to the Game instead of exiting the process
    # (engagement F2): a hit costs one of the lives, the ship respawns
    # invulnerable, and the run ends only at zero lives. Invulnerability is
    # checked before any hit is resolved, so a respawning ship can sit on
    # an asteroid for the grace window without losing another life.
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
                break  # the hit killed the asteroid; skip its remaining shots


def main():
    pygame.init()
    game_clk = pygame.time.Clock()
    dt = 0
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = updatable
    asteroid_field = AsteroidField()

    Player.containers = (updatable, drawable)
    player1 = Player(SCREEN_WIDTH/2, SCREEN_HEIGHT/2 )
    game = Game(player1, asteroids, shots)

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
                elif event.key == pygame.K_q:
                    pygame.quit()
                    return

        ms = game_clk.tick(60)
        dt = compute_dt(ms)
        updatable.update(dt)
        # player1.update(dt)

        handle_collisions(asteroids, shots, player1, game)
        
        screen.fill("black")

        for each in drawable:
            each.draw(screen)
        # player1.draw(screen)

        draw_hud(screen, game.score, lives=game.lives)
        if game.state == "game_over":
            draw_game_over(screen, game.score, new_high=game.new_high)

        pygame.display.flip()
        


if __name__ == "__main__":
    main()
