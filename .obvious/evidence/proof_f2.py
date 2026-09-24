"""F2 evidence: game-over overlay + respawn blink, headless (engagement F2).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/:

- f2_game_over.png    the game-over overlay: final score, new-high state, R/Q prompt
- f2_blink_visible.png  respawn grace window, visible half-cycle of the blink
- f2_blink_hidden.png   respawn grace window, hidden half-cycle of the blink
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from constants import SCREEN_HEIGHT, SCREEN_WIDTH
from game import Game
from hud import draw_hud, draw_game_over, load_save
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots = (pygame.sprite.Group() for _ in range(4))
Asteroid.containers = (asteroids, updatable, drawable)
Player.containers = (updatable, drawable)
player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots)


def render_frame():
    """One full main-loop frame, minus the event pump."""
    screen.fill("black")
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives)


# --- Scenario A: game-over overlay with the new-high-score state ---
existing_high = load_save()["high_score"]
game.add_score(existing_high + 1250)  # guarantee a genuine record-beat every run
for _ in range(3):
    game.player_hit()  # drain three lives -> game_over
Asteroid(300, 200, 60)  # backdrop rocks behind the overlay
Asteroid(900, 500, 40)
render_frame()
draw_game_over(screen, game.score, new_high=game.new_high)
pygame.image.save(screen, f"{OUT}/f2_game_over.png")

# --- Scenario B: respawn blink, both half-cycles ---
game.restart()  # counters reset, world cleared, ship centered
player.respawn()  # fresh 2s grace window
asteroids.empty()  # keep the blink frames clean: ship and HUD only
player.invulnerability_timer = 2.0  # visible half-cycle
render_frame()
pygame.image.save(screen, f"{OUT}/f2_blink_visible.png")

player.invulnerability_timer = 2.0 - 0.5 / 4  # hidden half-cycle (1.875s left)
render_frame()
pygame.image.save(screen, f"{OUT}/f2_blink_hidden.png")

print(
    f"game state={game.state!r} score={game.score} lives={game.lives} "
    f"saved={sorted(f for f in os.listdir(OUT) if f.startswith('f2_'))}"
)
