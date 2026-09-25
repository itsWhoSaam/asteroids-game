"""Run-stats evidence: the end-of-run summary block on the game-over screen
(run-stats PR).

Follows the proof_popups pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
kill paths (main.handle_collisions, the chip kill, maybe_advance_wave) plus
the real R-branch restart (main.restart_run):

- stats_game_over_summary.png   a played run's summary under the game-over
                                overlay: accuracy, tiers, waves, credits by
                                source — worst-case three-line overlay above
- stats_fresh_restart_summary.png  a fresh run's zeroed summary after the
                                R-branch hook, the passive-run wording

The run asserts the counters, both restart-hook resets, the exact summary
wording, the PR #36 points popup still floating at the sweep's kill site,
and summary-band pixels before each save, so a failing claim fails the
script.
"""

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
from constants import (
    CHIP_HEALTH_PER_TIER,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import WaveBanner, draw_game_over, draw_hud, draw_run_summary, points_for
from main import (
    FloatingText,
    handle_collisions,
    maybe_advance_wave,
    mint_destructions,
    restart_run,
)
from player import Player
from shot import Shot
from stats import SOURCE_CLICK, SOURCE_IDLE

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

random.seed(11)  # deterministic bursts, split children, and drop rolls

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
floaters = pygame.sprite.Group()
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
FloatingText.containers = (floaters, updatable, drawable)
Player.containers = (updatable, drawable)
AsteroidField.containers = updatable

player = Player(140, 620)  # parked away from the kill sites and the summary band
game = Game(player, asteroids, shots, powerups,
            save_path=os.path.join(OUT, "stats_save.json"))
economy = Economy(save_path=os.path.join(OUT, "stats_save.json"))
field = AsteroidField(game)
banner = WaveBanner()


def render_frame():
    """One full main-loop render, minus the event pump."""
    screen.fill(PALETTE["paper"])
    for each in drawable:  # pass 2: entities
        each.draw(screen)
    for each in floaters:  # pass 3: fx — bursts and floating popups
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    draw_game_over(screen, game.score, new_high=game.new_high)
    draw_run_summary(screen, game.stats)


# --- Scenario A: a played run's summary under the game-over overlay ---------
game.add_score(1250)  # beat the fresh save's 0 — the 3-line worst case above

for _ in range(3):  # three live-trigger pulls that miss: 3 fired, 0 hit
    player.shoot()
    player.shot_cooldown_timer = 0

rock = Asteroid(640, 360, 40)  # the aimed shot kills it: medium tier, 50 pts
player.shoot()  # the aimed kill shot — a fourth real trigger pull
aimed = shots.sprites()[-1]
aimed.position = pygame.Vector2(640, 360)  # walked onto the wreck site for the sweep
prev = set(asteroids)  # the main loop snapshots the previous frame

handle_collisions(asteroids, shots, player, game, powerups)

pts_popups = [f for f in floaters if f.label.endswith("pts")]
assert len(pts_popups) == 1, "PR #36's points popup still floats at the kill site"
for wreck, payout in mint_destructions(prev, asteroids, economy, game.stats):
    pass  # payouts float through the loop's own styled path in main

assert game.stats.shots_fired == 4
assert game.stats.shots_hit == 1
assert game.score == 1250 + points_for(40) == 1300
assert economy.credits == 50.0

chip_rock = Asteroid(900, 500, 20)  # a click finishes a small rock: 100 cr
prev = set(asteroids)
chip_rock.take_chip(CHIP_HEALTH_PER_TIER)
for wreck, payout in mint_destructions(prev, asteroids, economy, game.stats):
    pass

for child in list(asteroids):  # proof scaffolding: the split children drift on
    child.kill()  # — clear them so the field reads empty for the wave guard

field.spawn(60, pygame.Vector2(100, 100), pygame.Vector2(10, 0)).kill()
maybe_advance_wave(game, field, banner)  # the field cleared: wave 2 survived

assert game.stats.waves_survived == 1 and game.wave == 2
assert game.stats.destroyed == {"small": 1, "medium": 1, "large": 0}
assert game.stats.credits_idle == 50.0
assert game.stats.credits_click == 100.0
assert game.stats.summary_lines() == [
    "Shots: 1/4 hit (25%)",
    "Rocks destroyed: 1 small, 1 medium, 0 large",
    "Waves survived: 1",
    "Credits earned: 150 (idle 50, click 100)",
]

for _ in range(3):
    game.player_hit()  # drain three lives -> game over
assert game.state == "game_over"

for floater in list(floaters):  # expired: the summary reads on its own
    floater.kill()
for shot in list(shots):  # the misses too — a clean overlay frame
    shot.kill()

render_frame()
pygame.image.save(screen, f"{OUT}/stats_game_over_summary.png")

# The summary's seat, measured: the overlay's worst case ends ~445, the gap
# 446..476 reads paper, the block paints 478..628, and paper resumes below
# 630 — clear of the shop panel's 656 top edge.
gap = [screen.get_at((x, y)) for y in range(448, 476, 4) for x in range(340, 940, 8)]
assert all(pixel == (*PALETTE["paper"], 255) for pixel in gap), "no overlap"
band = [screen.get_at((x, y)) for y in range(480, 630, 4) for x in range(340, 940, 8)]
assert any(pixel != (*PALETTE["paper"], 255) for pixel in band), "summary paints"
below = [screen.get_at((x, y)) for y in range(632, 656, 4) for x in range(340, 940, 8)]
assert all(pixel == (*PALETTE["paper"], 255) for pixel in below), "clear of the shop"


# --- Scenario B: the R-branch restart zeroes the run, fresh zeros render ----
stats_before = game.stats
assert stats_before.shots_fired == 4  # the played run's counters are loaded

restart_run(game, economy, field, banner, asteroids)  # exactly what R runs

assert game.stats is stats_before  # reset in place — the player keeps the sink
assert player.stats is stats_before
assert stats_before.shots_fired == 0
assert stats_before.credits_earned == 0.0
assert len(asteroids) == 0

for _ in range(3):
    game.player_hit()  # an untouched run ends: the all-zeros summary
assert game.state == "game_over"

render_frame()
pygame.image.save(screen, f"{OUT}/stats_fresh_restart_summary.png")

band = [screen.get_at((x, y)) for y in range(480, 630, 4) for x in range(340, 940, 8)]
assert any(pixel != (*PALETTE["paper"], 255) for pixel in band), "zeros paint too"

save = json.load(open(os.path.join(OUT, "stats_save.json")))
assert not any("stat" in key for key in save), "run stats never persist"

print("run-stats evidence saved:", sorted(f for f in os.listdir(OUT) if f.startswith("stats_")))
