"""F5 evidence: explosion particles and screen shake, headless (engagement F5).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
collision sweep (main.handle_collisions) and run state (Game.player_hit):

- f5_before_burst.png  a large rock alive, one frame before destruction
- f5_burst.png         the same scene after the real sweep killed it: the
                       size-scaled debris cloud spread around the death site
- f5_shake_a.png       the frame of a player death — world blitted at the
                       first shaken offset
- f5_shake_b.png       the next frame — a different offset (same world, the
                       draw origin moved, entities didn't; the world sits
                       visibly shifted between the two frames)

No new events: F5 is a continuous effect, not a milestone — the sweep still
logs the usual asteroid_shot / player_hit types.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from constants import ASTEROID_MAX_RADIUS, SCREEN_HEIGHT, SCREEN_WIDTH
from game import Game
from hud import draw_hud
from main import handle_collisions
from particles import Particle, Shake
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups, particles = (
    pygame.sprite.Group() for _ in range(6)
)
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
Particle.containers = (particles, updatable, drawable)
Player.containers = (updatable, drawable)

shake = Shake()
player = Player(100, 660)  # out of scenario A's blast radius: no stray hit
game = Game(player, asteroids, shots, powerups, particles=particles, shake=shake)


def render_frame():
    """The main loop's render, verbatim: world surface, shaken blit, HUD."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    world.fill("black")
    for each in drawable:
        each.draw(world)
    offset = shake.offset()
    screen.fill("black")
    screen.blit(world, offset)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    return offset


# --- Scenario A: a large rock dies into a size-scaled burst -------------------
Asteroid(640, 360, ASTEROID_MAX_RADIUS)
Shot(640, 360)  # overlapping: destroys it this sweep
render_frame()  # the rock, whole — calm frame, zero offset
pygame.image.save(screen, f"{OUT}/f5_before_burst.png")

handle_collisions(asteroids, shots, player, game, powerups, shake)
assert len(asteroids) == 2  # the large rock split into two children
assert len(particles) > 0, "the parent must burst right before splitting"
updatable.update(0.1)  # let the cloud spread before the capture
render_frame()  # the debris cloud around the death site, world mildly shaken
pygame.image.save(screen, f"{OUT}/f5_burst.png")

# --- Scenario B: a player death rocks the screen across frames ---------------
for sprite in list(particles) + list(asteroids):  # clean slate for B
    sprite.kill()
shake.magnitude = 0.0
Asteroid(100, 660, 40)  # overlapping the ship: the real death path fires
Asteroid(180, 360, ASTEROID_MAX_RADIUS)  # near the left edge: the gap shows
game.player_hit()  # the real death path: burst + strong kick, lives 3 -> 2
assert shake.magnitude > 0 and game.lives == 2
updatable.update(0.1)  # spread the death cloud off the hull

offset_a = render_frame()
pygame.image.save(screen, f"{OUT}/f5_shake_a.png")

shake.update(1 / 60)  # decay one frame, then a fresh random direction
offset_b = render_frame()
pygame.image.save(screen, f"{OUT}/f5_shake_b.png")

print(f"F5 evidence written to {OUT}:")
for name in ("f5_before_burst.png", "f5_burst.png", "f5_shake_a.png", "f5_shake_b.png"):
    print(f"  {OUT}/{name}")
print(f"shake offsets across frames: a={offset_a} b={offset_b} "
      f"(magnitude {shake.magnitude:.1f} after decay)")
assert offset_a != offset_b, "two shaken frames must offset differently"
