"""PR-3 chaos evidence: mystery & curse pickups, headless (insanity chaos).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
collision sweep (main.handle_collisions) so powerup_spawned(mystery) /
mystery_collected / curse_revealed / powerup_collected(bomb) events land in
the repo-root game_events.jsonl:

- chaos_mystery_drop.png  a violet ? pickup drifting where a medium rock
                          died (both rolls patched deterministic)
- chaos_curse_reveal.png  the frame after the ship collects that ? and the
                          roll lands on the REVERSE curse — annotated, because
                          the curse is behavioral (controls answer backwards):
                          an unannotated frame would look like empty space
- chaos_bomb_clear.png    the frame after a ? resolves to the BOMB: the
                          whole field gone, the burst still on screen

Self-checks: the ? stamps violet pixels (its palette entry), the curse
reveal flips the controls and logs, and the bomb empties the field through
the bought nuke's exact path.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame
import random

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from hud import draw_hud
from main import HitStop, bomb_clear, handle_collisions
from particles import Particle, Shake
from player import Player
from powerups import PowerUp, PowerUpType
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
particles = pygame.sprite.Group()
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
PowerUp.containers = (powerups, updatable, drawable)
Particle.containers = (particles, updatable, drawable)
Player.containers = (updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, powerups)


def render_frame():
    """One full main-loop render, minus the event pump."""
    screen.fill("black")
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)


def violet_stamp_present(center):
    """Whether the ? glyph stamped its violet identity color nearby."""
    cx, cy = int(center[0]), int(center[1])
    violet = (*PALETTE["powerup_mystery"], 255)
    return any(
        screen.get_at((cx + dx, cy + dy)) == violet
        for dx in range(-8, 9, 2)
        for dy in range(-8, 9, 2)
    )


def patched_rolls(values):
    """Patch random.random to a deterministic iterator, restored after."""
    rolls = iter(values)
    real_random = random.random
    random.random = lambda: next(rolls)
    return real_random  # call this to restore


# --- Scenario A: a deterministic mystery drop — a violet ? appears ------------
Asteroid(400, 360, ASTEROID_MIN_RADIUS * 2)  # medium: eligible to drop
Shot(400, 360)  # overlapping: destroys it this sweep
restore = patched_rolls([0.0, 0.2])  # roll 1: drop; roll 2: < 0.40 → the wildcard
try:
    handle_collisions(asteroids, shots, player, game, powerups)
finally:
    random.random = restore
assert len(powerups) == 1, "the winning drop roll must pay exactly one pickup"
pickup = next(iter(powerups))
assert pickup.kind is PowerUpType.MYSTERY, "roll 0.2 must land on the ? wildcard"
render_frame()
assert violet_stamp_present(pickup.position), "the ? must stamp violet pixels"
pygame.image.save(screen, f"{OUT}/chaos_mystery_drop.png")

# Strike scenario A's stage: the rock's split-children and burst debris never
# tick (no update loop here) and would photobomb every later frame.
for rock in list(asteroids):
    rock.kill()
for spark in list(particles):
    spark.kill()

# --- Scenario B: the ship collects the ? — the roll lands on a curse ---------
pickup.position = player.position  # drift it onto the ship
restore = patched_rolls([0.1])  # the open: < 0.25 → the sting → REVERSE
try:
    handle_collisions(asteroids, shots, player, game, powerups)
finally:
    random.random = restore
assert player.cursed_reverse, "a 0.1 mystery open must reveal the REVERSE curse"
assert len(powerups) == 0, "the ? is consumed by its own reveal"
render_frame()
# The REVERSE reveal is behavioral — the controls answer backwards, no flash
# effect exists — so annotate the frame: bare black would prove nothing.
note = pygame.font.Font(None, 30).render(
    "REVERSE revealed — controls answer backwards (cursed_reverse)",
    True,
    PALETTE["powerup_mystery"],
    (20, 12, 28),
)
screen.blit(note, note.get_rect(midbottom=(SCREEN_WIDTH / 2, SCREEN_HEIGHT - 30)))
pygame.image.save(screen, f"{OUT}/chaos_curse_reveal.png")

# --- Scenario C: another ? resolves to the BOMB — the field clears -----------
for x in (200.0, 400.0, 600.0):
    Asteroid(x, 200, ASTEROID_MIN_RADIUS * 3)
PowerUp(player.position.x, player.position.y, PowerUpType.MYSTERY)
hit_stop = HitStop()
shake = Shake()
player.bomb_field = lambda: bomb_clear(hit_stop, shake, asteroids)
restore = patched_rolls([0.9])  # the open: a buff draw → BOMB
try:
    handle_collisions(asteroids, shots, player, game, powerups)
finally:
    random.random = restore
assert len(asteroids) == 0, "the bomb must clear the whole field"
assert hit_stop.frozen, "a multi-death frame must freeze for a beat"
render_frame()  # the burst debris is still on screen this frame
pygame.image.save(screen, f"{OUT}/chaos_bomb_clear.png")

print(f"Chaos evidence written to {OUT}:")
for name in ("chaos_mystery_drop.png", "chaos_curse_reveal.png", "chaos_bomb_clear.png"):
    print(f"  {OUT}/{name}")
print(
    "Events logged this session: powerup_spawned(mystery), mystery_collected, "
    "curse_revealed(reverse), mystery_collected, powerup_collected(bomb)"
)
