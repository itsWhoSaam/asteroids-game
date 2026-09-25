"""Daily-challenge evidence (Tier 3): the D toggle, the date-seeded spawn
path, the per-date best, and the mode's HUD/menu surfaces.

Follows the proof_difficulty pattern — a bounded scripted session under
SDL dummy drivers that saves PNG screenshots to /tmp/obv-evidence/ and
drives the real paths (Game.toggle_daily, main.restart_run's seeding, the
field's real update loop, hud's save merge):

- daily_menu_off.png    the boot menu with the daily row (best 0, off)
- daily_menu_on.png     after D: the row marked `< on`
- daily_running.png     the seeded run: gold DAILY CHALLENGE tag, WAVE 1
- daily_replay.png      the R retry mid-sequence (same spawns re-rolling)
- daily_gameover.png    the game-over prompt advertising D daily

The script asserts the date→seed purity, the same-seed spawn-sequence
replay, divergence on a different seed, the merge-safe daily_best write,
and the tag's gold pixels before each save, so a failing claim fails the
script.
"""

import datetime
import json
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from asteroidfield import AsteroidField
from challenge import daily_seed, daily_slug, load_daily_best, utc_today
from constants import (
    DAILY_TAG_ROW,
    HUD_LINE_STEP,
    HUD_MARGIN,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import (
    WaveBanner,
    daily_menu_line,
    draw_game_over,
    draw_hud,
    draw_mode_menu,
    game_over_lines,
    mode_menu_lines,
)
from main import restart_run, select_mode
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)
SAVE = f"{OUT}/daily_save.json"
if os.path.exists(SAVE):
    # A prior run's save would steer the boot menu — proofs are
    # deterministic, so start from a clean slate.
    os.remove(SAVE)

DAY = utc_today()
STEP_DT = 0.5  # half-second frames: wave 1's 2.5 s interval spawns every 5th

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
economy = Economy(save_path=SAVE)
field = AsteroidField(game)
banner = WaveBanner()


def render_frame():
    """One full main-loop render minus the event pump and the sweep —
    the HUD carries the daily tag whenever the mode is armed."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             daily=game.daily)
    return screen


def spawn_sequence(frames):
    """(class, radius, x, y, vx, vy) for every spawn the field's real
    update path makes over the next `frames` frames."""
    sequence = []
    for _ in range(frames):
        before = set(asteroids)
        field.update(STEP_DT)
        for rock in asteroids:
            if rock not in before:
                sequence.append(
                    (type(rock).__name__, rock.radius,
                     rock.position.x, rock.position.y,
                     rock.velocity.x, rock.velocity.y)
                )
    return sequence


def daily_tag_band():
    """The top-right row region where the DAILY CHALLENGE tag seats."""
    return [
        (x, HUD_MARGIN + DAILY_TAG_ROW * HUD_LINE_STEP + dy)
        for x in range(SCREEN_WIDTH - 260, SCREEN_WIDTH - HUD_MARGIN)
        for dy in range(0, 30)
    ]


# --- Scenario A: the boot menu — the daily row, off, best 0 ------------------
game.state = "menu"  # main()'s boot state (the Game still constructs playing)
rows = mode_menu_lines(game.mode, game.high_scores)
assert len(rows) == 3, rows
daily_row = daily_menu_line(game.daily, game.daily_best)
assert daily_row.startswith("D  DAILY CHALLENGE"), daily_row
assert "best 0" in daily_row and "< on" not in daily_row, daily_row
render_frame()
draw_mode_menu(screen, game.mode, game.high_scores,
               daily=game.daily, daily_best=game.daily_best)
pygame.image.save(screen, f"{OUT}/daily_menu_off.png")

# --- Scenario B: D arms the challenge — the row flips to `< on` --------------
assert game.toggle_daily() is True
assert game.daily is True
daily_row = daily_menu_line(game.daily, game.daily_best)
assert "< on" in daily_row, daily_row
render_frame()
draw_mode_menu(screen, game.mode, game.high_scores,
               daily=game.daily, daily_best=game.daily_best)
pygame.image.save(screen, f"{OUT}/daily_menu_on.png")

# --- Scenario C: 2 launches NORMAL — the run is seeded from the UTC date -----
select_mode(game, economy, field, banner, asteroids, "normal")
assert game.state == "playing" and game.mode == "normal"
assert game.daily is True, "selection must survive the launch hook"
assert game.daily_day == DAY, (game.daily_day, DAY)
# The field draws from a seeded generator — the day-seed provenance is
# pinned by the test suite; this proof's replay (scenario D) is the
# observable. No draws are burned here: the capture below must start a
# fresh generator's stream at draw 0 so the retry can reproduce it.
assert isinstance(field.rng, random.Random)
first_sequence = spawn_sequence(300)  # ~60 spawns across wave 1
assert len(first_sequence) >= 20, len(first_sequence)
render_frame()  # mid-run: the tag rides the HUD's top-right column
band = daily_tag_band()
gold = (*PALETTE["daily_gold"], 255)
assert any(screen.get_at(pos) == gold for pos in band), "no gold tag pixels"
banner.draw(screen)
pygame.image.save(screen, f"{OUT}/daily_running.png")

# --- Scenario D: the R retry replays the same spawn sequence ------------------
game.state = "game_over"  # as if the run had ended
restart_run(game, economy, field, banner, asteroids)
assert game.daily is True and game.daily_day == DAY
replay = spawn_sequence(300)
assert replay == first_sequence, "the retry's spawns diverged from the day's"
render_frame()
banner.draw(screen)
pygame.image.save(screen, f"{OUT}/daily_replay.png")

# --- Scenario E: a different day's seed diverges ------------------------------
other = DAY + datetime.timedelta(days=1)
probe = sum(
    1 for a, b in zip(
        (random.Random(daily_seed(DAY)).random() for _ in range(300)),
        (random.Random(daily_seed(other)).random() for _ in range(300)),
    ) if a == b
)
assert probe < 300, "a different day's seed replayed today's draws"

# --- Scenario F: game over records the day's best through the merge -----------
game.add_score(1500)
game.game_over()
assert game.state == "game_over"
assert load_daily_best(DAY, path=SAVE) == 1500, "the day's best didn't record"
with open(SAVE) as fh:
    data = json.load(fh)
assert data["daily_best"] == {daily_slug(DAY): 1500}, data["daily_best"]
prompt = game_over_lines(game.score, new_high=True, mode=game.mode)
assert prompt[-1] == "R restart - 1/2/3 mode (NORMAL) - D daily - Q quit", prompt
render_frame()
draw_game_over(screen, game.score, new_high=True, mode=game.mode)
pygame.image.save(screen, f"{OUT}/daily_gameover.png")

print(f"daily challenge evidence written to {OUT}:")
print(f"  date={DAY} slug={daily_slug(DAY)} seed={daily_seed(DAY)}")
print(f"  replayed spawns={len(first_sequence)} probe_matches={probe}/300")
print(f"  daily_best={data['daily_best']}")
