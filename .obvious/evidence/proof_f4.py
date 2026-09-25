"""F4 evidence: timed power-ups, headless (engagement F4).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
collision sweep (main.handle_collisions) so powerup_spawned /
powerup_collected events land in the repo-root game_events.jsonl:

- f4_pickup.png      a RAPID pickup drifting where a medium rock died (the
                     drop roll is patched deterministic for the one sweep)
- f4_shield_ring.png the ship wearing the shield ring after collecting a
                     SHIELD pickup through the real sweep
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame
import random

from asteroid import Asteroid
from constants import ASTEROID_MIN_RADIUS, SCREEN_HEIGHT, SCREEN_WIDTH
from game import Game
from hud import draw_hud
from main import handle_collisions
from player import Player
from powerups import PowerUp, PowerUpType
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
PowerUp.containers = (powerups, updatable, drawable)
Player.containers = (updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, powerups)


def render_frame():
    """One full main-loop render, minus the event pump."""
    screen.fill("black")
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)


# --- Scenario A: a deterministic drop — a medium rock dies, a pickup appears ---
Asteroid(400, 360, ASTEROID_MIN_RADIUS * 2)  # medium: eligible to drop
Shot(400, 360)  # overlapping: destroys it this sweep
rolls = iter([0.0, 0.5])  # roll 1: drop fires; roll 2: the buff draw (kind unpinned)
real_random = random.random
random.random = lambda: next(rolls)
try:
    handle_collisions(asteroids, shots, player, game, powerups)
finally:
    random.random = real_random
assert len(powerups) == 1, "the winning drop roll must pay exactly one pickup"
assert not player.shielded  # the RAPID pickup is away from the ship: uncollected
render_frame()
pygame.image.save(screen, f"{OUT}/f4_pickup.png")

# --- Scenario B: the ship collects a SHIELD and wears the ring ---
PowerUp(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2, PowerUpType.SHIELD)  # on the ship
handle_collisions(asteroids, shots, player, game, powerups)  # real random: collection
assert player.shielded, "overlapping SHIELD must collect and stock the ring"
assert len(powerups) == 1  # only the uncollected RAPID pickup remains
render_frame()
pygame.image.save(screen, f"{OUT}/f4_shield_ring.png")

print(f"F4 evidence written to {OUT}:")
for name in ("f4_pickup.png", "f4_shield_ring.png"):
    print(f"  {OUT}/{name}")
print("Events logged this session: powerup_spawned(shield), powerup_collected(shield)")
