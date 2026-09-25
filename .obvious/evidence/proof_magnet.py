"""Magnet-powerup evidence (Tier 3): collecting the MAGNET drop starts an
8 s clock that bends drifting pickups and credit floats toward the ship —
a force applied to velocity, never a teleport — with a MAGNET Ns HUD tag
on the lives/wave hidden-while-zero pattern.

Follows the proof_popups pattern — a bounded scripted session under SDL
dummy drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives
the real paths (the sweep's pickup collection, the pull step apply_magnet,
the FloatingText dt-timer):

- magnet_before_pull.png   the credit float rising straight, the green M
                           drop sitting uncollected, no tag, no pull
- magnet_pull_active.png   the same scene 0.75 s later: the float and the
                           triple pickup bent toward the hull, the MAGNET
                           7s tag top-right in the effect's green

The run asserts the drop roll landed MAGNET, collection started the clock,
the pull bends only pullable bodies, points popups hold their line, and
every pulled body closed distance before each save, so a failing claim
fails the script. The drop-roll path itself is pinned in tests/test_magnet.py.
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from constants import PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH
from economy import Economy
from game import Game
from hud import draw_hud
from main import (
    FloatingText,
    apply_magnet,
    draw_credits,
    handle_collisions,
    magnet_pullables,
    popup_style,
)
from player import Player
from powerups import PowerUp, PowerUpType

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

random.seed(11)  # deterministic bursts

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
floaters = pygame.sprite.Group()
PowerUp.containers = (powerups, updatable, drawable)
FloatingText.containers = (floaters, updatable, drawable)
Player.containers = (updatable, drawable)

player = Player(420, 420)  # the pull's attractor
game = Game(player, asteroids, shots, powerups)
economy = Economy(save_path=os.path.join(OUT, "magnet_save.json"))

CREDIT_STYLE = popup_style("credits", 50)
POINTS_STYLE = popup_style("points", 50)
CREDIT_SPOT = pygame.Vector2(620, 380)
POINTS_SPOT = pygame.Vector2(620, 340)


def render_frame():
    """One full main-loop render, minus the event pump."""
    screen.fill(PALETTE["paper"])
    for each in drawable:  # pass 2: entities
        each.draw(screen)
    for each in floaters:  # pass 3: fx — bursts and floating popups
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             magnet=player.magnet_timer if player.has_magnet else 0.0)
    draw_credits(screen, economy.credits)


def spawn_floats():
    """The scene's two floats exactly as the loop spawns them."""
    FloatingText(CREDIT_SPOT.x, CREDIT_SPOT.y, 50, label=CREDIT_STYLE.label,
                 color=CREDIT_STYLE.color, magnetic=CREDIT_STYLE.magnetic)
    FloatingText(POINTS_SPOT.x, POINTS_SPOT.y, 50, label=POINTS_STYLE.label,
                 color=POINTS_STYLE.color, magnetic=POINTS_STYLE.magnetic)


# --- Scenario A: before — floats rise straight, no magnet, no tag ------------
magnet_drop = PowerUp(420, 420, PowerUpType.MAGNET)  # sitting on the hull
triple = PowerUp(660, 470, PowerUpType.TRIPLE)  # drifting inside the band
triple.velocity = pygame.Vector2(0, 0)  # at rest: the pull's motion is unambiguous
spawn_floats()

assert not player.has_magnet and player.magnet_timer == 0.0
assert triple.velocity == pygame.Vector2(0, 0)
render_frame()
pygame.image.save(screen, f"{OUT}/magnet_before_pull.png")

# --- Scenario B: collection starts the clock; the pull bends the bodies ------
for floater in list(floaters):
    floater.kill()  # rebuild the pair post-collection for a matched frame

handle_collisions(asteroids, shots, player, game, powerups)  # the real sweep
assert not any(p.kind is PowerUpType.MAGNET for p in powerups), "the sweep collected the drop"
assert player.has_magnet, "collecting MAGNET starts the 8 s clock"
assert abs(player.magnet_timer - 8.0) < 1e-9

spawn_floats()
credit, pts = floaters.sprites()[-2], floaters.sprites()[-1]
assert credit.label == CREDIT_STYLE.label and pts.label == POINTS_STYLE.label

apply_magnet(game, player, 1 / 60, magnet_pullables(powerups, floaters))
assert credit.velocity.x < 0, "the credit float bends toward the ship"
assert pts.velocity == pygame.Vector2(0, 0), "points popups hold their line"

ship = pygame.Vector2(player.position)
triple_start = (pygame.Vector2(triple.position) - ship).length()
credit_start = (pygame.Vector2(credit.position) - ship).length()
for _ in range(45):  # 0.75 s of flight under the pull
    apply_magnet(game, player, 1 / 60, magnet_pullables(powerups, floaters))
    for body in list(updatable):
        body.update(1 / 60)
assert (pygame.Vector2(triple.position) - ship).length() < triple_start, \
    "the pickup closed on the ship"
assert (pygame.Vector2(credit.position) - ship).length() < credit_start, \
    "the credit float closed on the ship"
assert 0.0 < player.magnet_timer < 8.0, "the clock ran but is not spent"
assert triple.alive(), "the pull gathers, it never slams past the hull"

render_frame()
pygame.image.save(screen, f"{OUT}/magnet_pull_active.png")

print("magnet evidence saved:", sorted(f for f in os.listdir(OUT) if f.startswith("magnet")))
