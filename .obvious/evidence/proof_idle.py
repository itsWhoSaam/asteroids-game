"""Idle-economy evidence: bounded headless run that exercises the shipped
click → chip → destruction-diff → mint pipeline and captures PNGs of the
floating '+N' credit number and the Credits HUD line to /tmp/obv-evidence/.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")

import pygame

from constants import (
    ASTEROID_MIN_RADIUS,
    CLICK_DAMAGE_BASE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from asteroid import Asteroid
from economy import Economy
from hud import draw_hud
from main import (
    FloatingText,
    asteroid_at,
    destroyed_asteroids,
    draw_credits,
)
from shot import Shot

os.makedirs("/tmp/obv-evidence", exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
clock = pygame.time.Clock()

updatable = pygame.sprite.Group()
drawable = pygame.sprite.Group()
asteroids = pygame.sprite.Group()
shots = pygame.sprite.Group()
floaters = pygame.sprite.Group()

Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
FloatingText.containers = (floaters, updatable, drawable)

economy = Economy()

# A deterministic field: one large rock to click-kill, one bystander.
victim = Asteroid(500, 360, ASTEROID_MIN_RADIUS * 3)  # large → 20 credits
Asteroid(900, 200, ASTEROID_MIN_RADIUS * 2)

# The real click path: pick under the cursor, chip it to death.
for _ in range(int(victim.chip_threshold)):
    target = asteroid_at(asteroids, (500, 360))
    assert target is victim, "cursor pick missed the victim"
    target.take_chip(CLICK_DAMAGE_BASE)

# The real destruction → mint → floater path, exactly as the main loop does.
prev = {victim}
destroyed = destroyed_asteroids(prev, asteroids)
assert len(destroyed) == 1 and destroyed[0] is victim
for wreck in destroyed:
    payout = economy.mint(wreck.radius)
    FloatingText(wreck.position.x, wreck.position.y, payout)

frames = 0
while frames < 60:  # 1 simulated second: the floater lives ~1s
    dt = clock.tick(60) / 1000
    updatable.update(dt)

    screen.fill("black")
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, 0, lives=3)
    draw_credits(screen, economy.credits)
    pygame.display.flip()

    if frames in (10, 30, 59):
        pygame.image.save(screen, f"/tmp/obv-evidence/idle_click_{frames}.png")
    frames += 1

print(
    f"ran {frames} frames, credits={economy.credits}, "
    f"floaters={len(floaters)} (expired by design), "
    f"asteroids={len(asteroids)} (victim's two children)"
)
