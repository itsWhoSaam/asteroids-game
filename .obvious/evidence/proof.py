import os, sys, time
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")
import pygame
from constants import SCREEN_WIDTH, SCREEN_HEIGHT
from asteroid import Asteroid
from asteroidfield import AsteroidField
from player import Player
from shot import Shot

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
clock = pygame.time.Clock()
updatable, drawable, asteroids, shots = (pygame.sprite.Group() for _ in range(4))
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
AsteroidField.containers = updatable
AsteroidField()
Player.containers = (updatable, drawable)
Player(SCREEN_WIDTH/2, SCREEN_HEIGHT/2)

frames = 0
while frames < 180:  # 3 simulated seconds at 60fps
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            pygame.image.save(screen, "/tmp/obv-evidence/frame.png"); sys.exit(0)
    dt = clock.tick(60)/1000
    updatable.update(dt)
    for a in list(asteroids):
        for s in list(shots):
            if a.collides_with(s):
                a.split(); s.kill()
    screen.fill("black")
    for d in drawable: d.draw(screen)
    if frames in (60, 120, 179):
        pygame.image.save(screen, f"/tmp/obv-evidence/frame_{frames}.png")
    frames += 1
print(f"ran {frames} frames, asteroids={len(asteroids)}, shots={len(shots)}")
