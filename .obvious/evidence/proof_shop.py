"""Shop evidence: bounded headless run that simulates purchases through the
real key path — handle_key → Economy seams → live effects — and captures
PNGs of the bottom shop panel (affordable cells bright, the rest dim) to
/tmp/obv-evidence/.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")

import pygame

from constants import (
    ASTEROID_MIN_RADIUS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHOP_BRIGHT_COLOR,
)
from asteroid import Asteroid
from economy import Economy
from game import Game
from hud import draw_hud
from main import FloatingText, click_damage, draw_credits
from player import Player
from shop import Shop
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
economy.credits = 500.0  # the harness funds the ledger; real runs earn it
player1 = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player1, asteroids, shots)
shop = Shop(economy, player1)

# A backdrop field so the panel reads as an overlay over live play.
Asteroid(300, 250, ASTEROID_MIN_RADIUS * 3)
Asteroid(800, 420, ASTEROID_MIN_RADIUS * 2)
Asteroid(1000, 200, ASTEROID_MIN_RADIUS)

# Purchases through the real key path, exactly as main()'s KEYDOWN branch
# runs them — including the confirmation float the branch spawns.
for key in (pygame.K_1, pygame.K_1, pygame.K_3, pygame.K_2, pygame.K_4):
    purchase = shop.handle_key(key)
    assert purchase is not None, f"key {key} should buy something with 500cr"
    x, y = shop.cell_center(purchase.name)
    FloatingText(x, y, 0, label=f"{purchase.title} Lv {purchase.level}",
                 color=SHOP_BRIGHT_COLOR)

# The wired effects are live: click damage up, cooldown down, income scaled.
assert click_damage(shop) == 1.0 * 1.8**2
assert player1.cooldown_mult == 0.88
assert economy.income_multiplier() == 1.15
assert economy.levels["drone"] == 1  # placeholder: stored, no gameplay yet

frames = 0
while frames < 60:
    dt = clock.tick(60) / 1000
    updatable.update(dt)

    screen.fill("black")
    for each in drawable:
        each.draw(screen)

    draw_hud(screen, game.score, lives=game.lives)
    draw_credits(screen, economy.credits)
    shop.draw_panel(screen)
    pygame.display.flip()

    if frames in (10, 30, 59):
        pygame.image.save(screen, f"/tmp/obv-evidence/shop_panel_{frames}.png")
    frames += 1

print(
    f"ran {frames} frames, credits={economy.credits:.1f} after 5 purchases, "
    f"click_damage={click_damage(shop)}, cooldown_mult={player1.cooldown_mult}, "
    f"income={economy.income_multiplier()}, drone_level={economy.levels['drone']}, "
    f"floaters={len(floaters)} (expired by design), asteroids={len(asteroids)}"
)
