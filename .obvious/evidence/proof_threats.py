"""Insanity-threats evidence (PR-2): one staged, bounded run per threat —
a tier-1 boss under fire with its health bar, a hostile saucer firing
aimed shots, and a live black hole bending the field. Saves PNGs to
/tmp/obv-evidence/ and asserts the threats are actually on screen.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

import pygame

from asteroid import Asteroid, Boss
from blackhole import BlackHole, live_holes
from constants import SCREEN_WIDTH, SCREEN_HEIGHT
from game import Game
from hud import draw_boss_bar
from player import Player
from saucer import Saucer, SaucerShot
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
clock = pygame.time.Clock()

updatable, drawable = pygame.sprite.Group(), pygame.sprite.Group()
asteroids, shots = pygame.sprite.Group(), pygame.sprite.Group()
powerups, saucers, enemy_shots = (
    pygame.sprite.Group(),
    pygame.sprite.Group(),
    pygame.sprite.Group(),
)

Asteroid.containers = (asteroids, updatable, drawable)
Boss.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
SaucerShot.containers = (enemy_shots, updatable, drawable)
Saucer.containers = (saucers, drawable)
BlackHole.containers = (updatable, drawable)
Player.containers = (updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, powerups)


def render(frame_name, boss=None):
    """One honest frame: sim tick, fill, draw everything, save."""
    dt = clock.tick(60) / 1000
    updatable.update(dt)
    screen.fill("black")
    for d in drawable:
        d.draw(screen)
    if boss is not None:
        draw_boss_bar(screen, boss)
    pygame.image.save(screen, f"{OUT}/{frame_name}")


# --- 1 · the boss under fire, with its health bar -------------------------------
game.wave = 5
boss = Boss(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3, 1)
boss.take_hit()  # one hit off full: the bar must show the drain
for dx in (-80, 0, 80):
    Shot(boss.position.x + dx, boss.position.y + 160)
frame = render("threats_boss.png", boss=boss)
assert boss.alive() and boss.hp < boss.max_hp
print(f"boss: hp {boss.hp}/{boss.max_hp}, radius {boss.radius:.0f}")
boss.kill()

# --- 2 · a hostile saucer firing -------------------------------------------------
game.wave = 2
saucer = Saucer(240, 200, "small")
saucer.fire_timer = 0.0  # fires this frame, aimed at the player
saucer.update(1 / 60, player, enemy_shots)
live_holes.clear()
frame = render("threats_saucer.png")
assert len(enemy_shots) == 1

# --- 3 · a live black hole bending the field -------------------------------------
game.wave = 3
hole = BlackHole(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
live_holes.append(hole)
for i in range(4):  # rocks drifting near the well
    Asteroid(SCREEN_WIDTH / 2 - 200 + i * 60, SCREEN_HEIGHT / 2 - 140, 30)
drift_shot = Shot(SCREEN_WIDTH / 2 + 260, SCREEN_HEIGHT / 2)
drift_shot.velocity = pygame.Vector2(400, 0)  # flying away from the well
for _ in range(20):  # a third of a second of gravity
    updatable.update(1 / 60)
for d in drawable:
    d.draw(screen)
pygame.image.save(screen, f"{OUT}/threats_blackhole.png")
assert hole.alive() and drift_shot.velocity.x < 400
print(f"blackhole: lifetime={hole.lifetime:.1f}, shot bent to x={drift_shot.velocity.x:.1f}")

print("threats evidence: 3 PNGs saved, all assertions passed")
