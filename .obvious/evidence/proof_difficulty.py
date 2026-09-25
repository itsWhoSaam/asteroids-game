"""Difficulty-modes evidence (Tier 2): Easy/Normal/Hard select on the
start/game-over flow — per-mode lives, spawns, and high scores, persisted.

Follows the proof_milestone pattern — a bounded scripted session under SDL
dummy drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives
the real selection path (main.select_mode, the pump's 1/2/3 handler) plus
the real field update, whose cadence now reads game.mode:

- difficulty_menu.png          the boot SELECT DIFFICULTY menu over the dim
- difficulty_easy_running.png  EASY launched: WAVE 1 banner, 5 lives on the HUD
- difficulty_hard_running.png  HARD launched: 2 lives, faster spawn band
- difficulty_hard_gameover.png HARD game-over prompt offering the 1/2/3 select

The run asserts the menu rows, the lives, the persisted mode and save key,
and the prompt text before each save, so a failing claim fails the script.
"""

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from asteroidfield import AsteroidField, wave_params
from constants import PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH
from economy import Economy
from game import Game
from hud import (
    WaveBanner,
    draw_game_over,
    draw_hud,
    draw_mode_menu,
    game_over_lines,
    mode_menu_lines,
)
from main import select_mode
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)
SAVE = f"{OUT}/difficulty_save.json"
if os.path.exists(SAVE):
    # A prior run's save would steer the boot menu (it ends with HARD
    # saved) — proofs are deterministic, so start from a clean slate.
    os.remove(SAVE)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (
    pygame.sprite.Group() for _ in range(5)
)
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
AsteroidField.containers = updatable
Player.containers = (updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, powerups, save_path=SAVE)
economy = Economy()
field = AsteroidField(game)
banner = WaveBanner()


def render_frame():
    """One full main-loop render minus the event pump and the sweep."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    return screen


# --- Scenario A: the boot menu over the still, empty field -------------------
# main() boots into the select state; nothing has spawned, so the menu dims
# the empty field and the ship.
game.state = "menu"  # main()'s boot state (the Game still constructs playing)
rows = mode_menu_lines(game.mode, game.high_scores)
assert len(rows) == 3, rows
assert rows[1].endswith("< saved"), rows  # Normal is the saved default
assert "5 lives" in rows[0] and "2 lives" in rows[2], rows
render_frame()
draw_mode_menu(screen, game.mode, game.high_scores)
pygame.image.save(screen, f"{OUT}/difficulty_menu.png")

# --- Scenario B: 1 launches EASY — WAVE 1 banner, 5 lives on the HUD ---------
select_mode(game, economy, field, banner, asteroids, "easy")
assert game.state == "playing", game.state
assert game.mode == "easy"
assert game.lives == 5, game.lives
assert banner.visible and banner.text == "WAVE 1", banner.text
game.add_score(200)  # the run scores — Easy's best and the legacy key both write
# The field's real spawn path reads the mode: EASY's interval is the shipped
# 2.5 s x1.25, so one 4 s step spawns exactly one slow-band rock.
assert wave_params(1, "easy")["spawn_interval"] > wave_params(1, "normal")["spawn_interval"]
field.update(4.0)
assert len(asteroids) == 1, len(asteroids)
field.spawn(55, pygame.Vector2(320, 280), pygame.Vector2(30, 20))  # a second rock
render_frame()
banner.draw(screen)
pygame.image.save(screen, f"{OUT}/difficulty_easy_running.png")

# --- Scenario C: 3 relaunches HARD mid-session — 2 lives ---------------------
# The menu's other select, from the same running session: selection persists
# to the save and applies at restart, so lives land on Hard's row.
select_mode(game, economy, field, banner, asteroids, "hard")
assert game.mode == "hard" and game.lives == 2, (game.mode, game.lives)
assert banner.text == "WAVE 1", banner.text
assert wave_params(1, "hard")["spawn_interval"] < wave_params(1, "easy")["spawn_interval"]
field.spawn(70, pygame.Vector2(900, 200), pygame.Vector2(-90, 40))
field.spawn(50, pygame.Vector2(760, 520), pygame.Vector2(-70, -30))
game.add_score(123)  # Hard's own best — worse than Easy's 200, must not win
render_frame()
banner.draw(screen)
pygame.image.save(screen, f"{OUT}/difficulty_hard_running.png")

# --- Scenario D: the HARD game-over prompt offers the 1/2/3 select -----------
game.game_over()
prompt = game_over_lines(game.score, new_high=False, mode="hard")
assert prompt == [
    f"Game over — score {game.score}",
    "R restart - 1/2/3 mode (HARD) - D daily - Q quit",
], prompt
render_frame()
draw_game_over(screen, game.score, new_high=False, mode=game.mode)
pygame.image.save(screen, f"{OUT}/difficulty_hard_gameover.png")

# --- Persistence: the choice and the per-mode bests rode the save merge ------
with open(SAVE) as fh:
    data = json.load(fh)
assert data["difficulty"] == "hard", data
assert data["high_score_easy"] == 200, data
assert data["high_score_hard"] == 123, data
# The legacy key keeps its old meaning: the overall best across modes.
assert data["high_score"] == 200, data

print("difficulty proof OK:", *(f"{n}.png" for n in (
    "difficulty_menu", "difficulty_easy_running",
    "difficulty_hard_running", "difficulty_hard_gameover",
)), sep="\n  ")
