import pygame
import sys

from constants import MAX_DT, SCREEN_WIDTH, SCREEN_HEIGHT
from asteroid import Asteroid
from asteroidfield import AsteroidField
from logger import log_state, log_event
from player import Player
from hud import Score, draw_hud, points_for
from shot import Shot


def compute_dt(ms):
    """Clamped frame delta: a stall (alt-tab, window drag) must never move
    entities far enough to skip over a collision unchecked."""
    return min(ms / 1000, MAX_DT)


def handle_collisions(asteroids, shots, player1, score=None):
    # score is the F1 seam; F2's Game object takes its place.
    for asteroid in asteroids:
        if not asteroid.alive():
            continue
        if asteroid.collides_with(player1):
            log_event("player_hit")
            print("Game over!")
            sys.exit()
        for shot in shots:
            if not shot.alive():
                continue
            if asteroid.collides_with(shot):
                log_event("asteroid_shot")
                asteroid.split()
                shot.kill()
                if score is not None:
                    score.add_score(points_for(asteroid.radius))
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
    score = Score()

    

    while True:
        log_state()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

        ms = game_clk.tick(60)
        dt = compute_dt(ms)
        updatable.update(dt)
        # player1.update(dt)

        handle_collisions(asteroids, shots, player1, score)
        
        screen.fill("black")

        for each in drawable:
            each.draw(screen)
        # player1.draw(screen)

        draw_hud(screen, score.current)

        pygame.display.flip()
        


if __name__ == "__main__":
    main()
