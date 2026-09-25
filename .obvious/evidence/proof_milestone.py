"""Milestone-rewards evidence (Tier 1): every 5th wave grants a shield
charge plus a flat credit bonus, announced in the wave banner.

Follows the proof_f3 pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
advance path (main.maybe_advance_wave) with the player and economy seams:

- milestone_wave4_plain.png   WAVE 4 flash: an ordinary wave, no grant
- milestone_wave5_banner.png  MILESTONE WAVE 5 - SHIELD +500 CR flash with
                              the shield ring already on the ship
- milestone_wave5_ring.png    the ring persists after the flash fades out

The run asserts the banner text, the stocked charge, and the ledger bonus
before each save, so a failing claim fails the script.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import MILESTONE_CREDIT_BONUS, PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH
from economy import Economy
from game import Game
from hud import WaveBanner, draw_hud
from main import maybe_advance_wave
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots = (pygame.sprite.Group() for _ in range(4))
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
AsteroidField.containers = updatable
Player.containers = (updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots)
economy = Economy()
field = AsteroidField(game)
banner = WaveBanner()
banner.show(game.wave)  # game start: WAVE 1


def render_frame():
    """One full main-loop render, minus the event pump and the sweep."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    banner.draw(screen)


def clear_and_advance():
    """One wave cycle: a rock spawns and dies (what split()/culling do), the
    cleared field advances with the player and economy seams attached."""
    field.spawn(60, pygame.Vector2(300, 300), pygame.Vector2(40, 0)).kill()
    maybe_advance_wave(game, field, banner, player, economy)


# --- Scenario A: wave 4 is ordinary — plain banner, no grant ---
while game.wave < 4:
    clear_and_advance()
assert game.wave == 4 and banner.visible
assert banner.text == "WAVE 4"
assert player.shield_hits == 0 and economy.credits == 0.0
render_frame()
pygame.image.save(screen, f"{OUT}/milestone_wave4_plain.png")

# --- Scenario B: wave 5 — the milestone announcement and the grant ---
clear_and_advance()
assert game.wave == 5 and banner.visible
assert banner.text == "MILESTONE WAVE 5 - SHIELD +500 CR"
assert player.shielded and player.shield_hits == 1
assert economy.credits == MILESTONE_CREDIT_BONUS
render_frame()
pygame.image.save(screen, f"{OUT}/milestone_wave5_banner.png")

# --- Scenario C: the flash fades; the kept charge rings on ---
banner.update(10.0)  # past the flash duration: fully faded out
assert game.wave == 5 and not banner.visible
assert player.shielded  # no duration clock: the charge is kept until spent
render_frame()
pygame.image.save(screen, f"{OUT}/milestone_wave5_ring.png")

print(
    f"wave={game.wave} shield_hits={player.shield_hits} "
    f"credits={economy.credits} banner='{banner.text}' "
    f"saved={sorted(f for f in os.listdir(OUT) if f.startswith('milestone_'))}"
)
