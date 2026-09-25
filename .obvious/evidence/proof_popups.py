"""Distinct-score-popups evidence (Tier 2): a shot kill's points award
floats its own white '+N pts' at the kill site while credits keep their
yellow '+N' — both on the FloatingText dt-timer template.

Follows the proof_milestone pattern — a bounded scripted session under SDL
dummy drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives
the real kill path (main.handle_collisions) plus the real destruction-diff
mint:

- popups_shot_kill_pair.png  the pair: white '+50 pts' a head above the
                             yellow '+50' credit float over the same wreck
- popups_credits_only.png    a chip kill: the yellow credit float alone
                             (chip kills pay no points, so no popup)

The run asserts both popup labels, colors, the SCORE_POPUP_OFFSET_Y stack,
and the single mint before each save, so a failing claim fails the script.
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    FLOAT_COLOR,
    PALETTE,
    SCORE_COLOR,
    SCORE_POPUP_OFFSET_Y,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import draw_hud, points_for
from main import (
    FloatingText,
    destroyed_asteroids,
    draw_credits,
    handle_collisions,
    popup_style,
)
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

random.seed(7)  # deterministic bursts, split children, and drop rolls

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
floaters = pygame.sprite.Group()
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
FloatingText.containers = (floaters, updatable, drawable)
Player.containers = (updatable, drawable)

player = Player(140, 620)  # parked far from the kill sites
game = Game(player, asteroids, shots, powerups)
economy = Economy(save_path=os.path.join(OUT, "popups_save.json"))


def render_frame():
    """One full main-loop render, minus the event pump."""
    screen.fill(PALETTE["paper"])
    for each in drawable:  # pass 2: entities
        each.draw(screen)
    for each in floaters:  # pass 3: fx — bursts and floating popups
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    draw_credits(screen, economy.credits)


# --- Scenario A: a shot kill floats the white pts popup over the credit ----
rock = Asteroid(640, 360, 40)  # medium tier → 50 points
Shot(640, 360)
prev = set(asteroids)  # the main loop snapshots the previous frame

handle_collisions(asteroids, shots, player, game, powerups)

score_popups = [f for f in floaters if f.label.endswith("pts")]
assert len(score_popups) == 1, "a shot kill floats exactly one pts popup"
popup = score_popups[0]
assert popup.label == f"+{points_for(40)} pts"
assert popup.color == SCORE_COLOR
assert game.score == points_for(40) == 50  # the award itself is unchanged

# The same-frame destruction diff mints once and floats the credit below.
destroyed = destroyed_asteroids(prev, asteroids)
assert len(destroyed) == 1 and destroyed[0] is rock
for wreck in destroyed:
    payout = economy.mint(wreck.radius)
    style = popup_style("credits", payout)
    FloatingText(wreck.position.x, wreck.position.y, payout,
                 label=style.label, color=style.color)
assert economy.credits == 50.0, "the kill paid exactly once"

credit_floats = [f for f in floaters if not f.label.endswith("pts")]
assert len(credit_floats) == 1
credit = credit_floats[0]
assert credit.label == "+50"
assert credit.color == FLOAT_COLOR != popup.color
assert popup.position.y == credit.position.y - SCORE_POPUP_OFFSET_Y

render_frame()
pygame.image.save(screen, f"{OUT}/popups_shot_kill_pair.png")

# --- Scenario B: a chip kill pays credits only — no pts popup --------------
for floater in list(floaters):
    floater.kill()
chip_rock = Asteroid(400, 560, ASTEROID_MIN_RADIUS * 3)  # large: 9.0 chip hp
prev = set(asteroids)
while chip_rock.alive():
    chip_rock.take_chip(3.0)  # three solid clicks, what an idle player does
destroyed = destroyed_asteroids(prev, asteroids)
assert len(destroyed) == 1 and destroyed[0] is chip_rock
for wreck in destroyed:
    payout = economy.mint(wreck.radius)
    FloatingText(wreck.position.x, wreck.position.y, payout)
assert game.score == 50, "chip kills pay credits, never points"
assert not [f for f in floaters if f.label.endswith("pts")], "no popup without a points award"

render_frame()
pygame.image.save(screen, f"{OUT}/popups_credits_only.png")

print("popup evidence saved:", os.listdir(OUT))
