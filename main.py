import pygame
import sys

from constants import SCREEN_WIDTH, SCREEN_HEIGHT
from asteroid import Asteroid
from asteroidfield import AsteroidField
from logger import log_state, log_event
from player import Player
from shot import Shot


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

    

    while True:
        log_state()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return

        ms = game_clk.tick(60)
        dt = ms/ 1000
        updatable.update(dt)
        # player1.update(dt)


        for asteroid in asteroids:
            for shot in shots:
                if asteroid.collides_with(player1):
                    log_event("player_hit")
                    print("Game over!")
                    sys.exit()
                if asteroid.collides_with(shot):
                    log_event("asteroid_shot")
                    asteroid.split()
                    shot.kill()
        
        screen.fill("black")

        for each in drawable:
            each.draw(screen)
        # player1.draw(screen)
        pygame.display.flip()
        


if __name__ == "__main__":
    main()
