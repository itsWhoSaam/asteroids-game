"""F3 evidence: wave progression, headless (engagement F3).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
advance path (main.maybe_advance_wave) so wave_started events land in the
repo-root game_events.jsonl:

- f3_wave1_banner.png  WAVE 1 flash at game start
- f3_wave2_banner.png  WAVE 2 flash right after clearing the populated field
- f3_wave3_hud.png     HUD wave slot reading Wave: 3 after the flash fades
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import SCREEN_HEIGHT, SCREEN_WIDTH
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
field = AsteroidField(game)
banner = WaveBanner()
banner.show(game.wave)  # game start: WAVE 1


def render_frame():
    """One full main-loop render, minus the event pump and the sweep."""
    screen.fill("black")
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    banner.draw(screen)


def clear_field():
    """Shoot every rock down: kill() is what split()/culling do to a sprite."""
    for asteroid in list(asteroids):
        asteroid.kill()


# --- Scenario A: WAVE 1 banner at game start (empty field, guard holds) ---
maybe_advance_wave(game, field, banner)  # must be a no-op: field never spawned
assert game.wave == 1 and banner.visible
render_frame()
pygame.image.save(screen, f"{OUT}/f3_wave1_banner.png")

# --- Scenario B: populated field cleared -> WAVE 2 flash ---
field.spawn(60, pygame.Vector2(300, 300), pygame.Vector2(40, 0))
clear_field()
maybe_advance_wave(game, field, banner)
assert game.wave == 2 and banner.visible
render_frame()
pygame.image.save(screen, f"{OUT}/f3_wave2_banner.png")

# --- Scenario C: flash fades to the HUD wave slot; the next advance re-arms ---
banner.update(10.0)  # past the flash duration: fully faded out
assert game.wave == 2 and not banner.visible
render_frame()
pygame.image.save(screen, f"{OUT}/f3_hud_wave2.png")

field.spawn(40, pygame.Vector2(300, 300), pygame.Vector2(40, 0))
clear_field()
maybe_advance_wave(game, field, banner)
assert game.wave == 3 and banner.visible  # every advance re-arms the flash
render_frame()
pygame.image.save(screen, f"{OUT}/f3_wave3_banner.png")

print(
    f"wave={game.wave} banner_visible={banner.visible} "
    f"saved={sorted(f for f in os.listdir(OUT) if f.startswith('f3_'))}"
)
