"""Achievements evidence: the toast banner over live play (Tier 2).

Follows the proof_stats pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
paths (Economy purchases, the pure evaluator, the toast queue):

- achievements_no_toast.png     live play before any unlock: the top-center
                                seat reads paper
- achievements_toast_slide.png  the FIRST NUKE toast mid-slide, still rising
- achievements_toast_seated.png the toast seated at its top-center seat,
                                over the field with HUD, credits, and shop
- achievements_toast_second.png after the first expires, the FIRST DRONE
                                toast seats — one at a time, FIFO

The script asserts the table-order unlocks, the pure slide geometry, the
FIFO handoff, seat-band pixels (nothing -> panel -> next panel), and the
save file's merge (achievements + idle_* + high_score all intact) before
each save, so a failing claim fails the script.
"""

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from achievements import Achievements, event_stats_from, toast_y
from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import (
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TOAST_SEAT_Y,
    TOAST_SLIDE_SECONDS,
    TOAST_SECONDS,
)
from economy import Economy
from game import Game
from hud import draw_hud
from main import draw_credits
from player import Player
from shop import Shop

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)
SAVE = os.path.join(OUT, "achievements_save.json")

# Pre-seed a high score above the display score, so the scripted add_score
# below never crosses — each scenario then controls exactly which award
# fires, and high_score_beaten stays untriggered for later waves to earn.
with open(SAVE, "w") as f:
    json.dump({"high_score": 99999, "muted": False, "volume": 100}, f)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

updatable = pygame.sprite.Group()
drawable = pygame.sprite.Group()
asteroids = pygame.sprite.Group()
shots = pygame.sprite.Group()
powerups = pygame.sprite.Group()

Asteroid.containers = (asteroids, updatable, drawable)
AsteroidField.containers = updatable
Player.containers = (updatable, drawable)

player = Player(200, 560)
game = Game(player, asteroids, shots, powerups, save_path=SAVE)
economy = Economy(save_path=SAVE)
shop = Shop(economy, player)
achievements = Achievements(save_path=SAVE)

# A small live-looking field (positions fixed; nothing steps — this is a
# render harness, not a simulation).
for x, y, radius in ((760, 220, 90), (1020, 480, 60), (560, 420, 35)):
    Asteroid(x, y, radius)
game.add_score(1250)

DT = 1 / 60


def render_frame():
    """One main-loop-ordered render: entities, HUD, credits, shop panel,
    powerup strip — then the achievements toast."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    draw_credits(screen, economy.credits)
    shop.draw_panel(screen)
    shop.draw_powerups(screen)
    achievements.draw(screen)


def seat_band():
    """Pixels across the toast's seated region (top-center seat)."""
    return [
        screen.get_at((x, y))
        for y in range(TOAST_SEAT_Y + 6, TOAST_SEAT_Y + 34, 4)
        for x in range(SCREEN_WIDTH // 2 - 140, SCREEN_WIDTH // 2 + 140, 8)
    ]


# --- Scenario A: live play before any unlock — the seat reads paper ---------
render_frame()
pygame.image.save(screen, f"{OUT}/achievements_no_toast.png")
assert all(pixel == (*PALETTE["paper"], 255) for pixel in seat_band()), \
    "the empty seat must read paper"

# --- Scenario B: the nuke unlocks; its toast slides in and seats ------------
economy.credits = 100000.0
assert economy.activate_powerup("nuke")
newly = achievements.evaluate(event_stats_from(game, economy))
assert [defn.id for defn in newly] == ["first_nuke"], "table-order unlock"

achievements.update(0.0)  # seat the queued toast at elapsed 0 (fully above)
for _ in range(int(TOAST_SLIDE_SECONDS / 2 / DT)):  # mid-slide, still rising
    achievements.update(DT)

panel_height = 40  # toast font 24 + 2 * PANEL_PAD_Y 8
mid_y = toast_y(achievements.toasts.elapsed, TOAST_SECONDS, panel_height)
assert -panel_height < mid_y < TOAST_SEAT_Y, "mid-slide is between hidden and seat"

render_frame()
pygame.image.save(screen, f"{OUT}/achievements_toast_slide.png")
for _ in range(int(TOAST_SLIDE_SECONDS / 2 / DT) + 1):  # finish the slide
    achievements.update(DT)
assert achievements.toasts.elapsed >= TOAST_SLIDE_SECONDS
assert toast_y(achievements.toasts.elapsed, TOAST_SECONDS, panel_height) == TOAST_SEAT_Y

render_frame()
pygame.image.save(screen, f"{OUT}/achievements_toast_seated.png")
assert all(pixel != (*PALETTE["paper"], 255) for pixel in seat_band()), \
    "the seated toast paints its panel over the seat"

# --- Scenario C: FIFO — the second award waits out the seated one -----------
assert economy.buy("drone")
newly = achievements.evaluate(event_stats_from(game, economy))
assert [defn.id for defn in newly] == ["first_drone"]
assert achievements.toasts.current == "FIRST NUKE", "one at a time: still seated"
assert achievements.toasts.queue == ["FIRST DRONE"], "queued, not swapped"

achievements.update(TOAST_SECONDS)  # the first toast expires off its clock
achievements.update(0.0)  # the queued one steps into the seat
assert achievements.toasts.current == "FIRST DRONE"
for _ in range(int(TOAST_SLIDE_SECONDS / DT) + 1):  # its own slide-in completes
    achievements.update(DT)
assert toast_y(achievements.toasts.elapsed, TOAST_SECONDS, panel_height) == TOAST_SEAT_Y

render_frame()
pygame.image.save(screen, f"{OUT}/achievements_toast_second.png")
assert all(pixel != (*PALETTE["paper"], 255) for pixel in seat_band())

# --- Scenario D: the save merged — achievements beside the idle keys --------
economy.save()  # the loop's autosave: idle_* keys join the file

save = json.load(open(SAVE))
assert save["achievements"] == ["first_drone", "first_nuke"]  # sorted ids
assert save["idle_levels"]["drone"] == 1
assert save["idle_powerup_uses"]["nuke"] == 1
assert save["high_score"] == 99999  # the pre-seeded record rides along

print("achievements evidence saved:",
      sorted(f for f in os.listdir(OUT) if f.startswith("achievements_")))
