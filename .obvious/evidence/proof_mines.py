"""Mine-asteroid evidence (Tier 3): a rare armed variant — dark hull,
blinking danger marker — that detonates when a shot kills it, paying
everything inside the blast radius through the ordinary seams.

Follows the proof_magnet pattern — a bounded scripted session under SDL
dummy drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives
the real paths (the field's armed-spawn roll, the sweep's shot-kill site,
main.detonate_mine, the destruction-diff mint):

- mine_armed_dark.png    the armed mine in the marker's dark half beside a
                         plain rock — the dark filled hull reads apart from
                         the outline-only tier rock
- mine_marker_lit.png    the same mine, marker in the lit half: the hostile
                         red blink that tells you what this rock is
- mine_detonation.png    after a shot kills the mine: the blast debris
                         cloud over the split neighbor's children, the rim
                         rock untouched

The run asserts the hull/marker pixels, the blast's victims (inside dead,
outside alive), the one-diff mint (mine + neighbor pay credits exactly
once, victims score-free), and the mine_detonated event, so a failing
claim fails the script. The paths themselves are pinned in
tests/test_mines.py.
"""

import json
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

import logger
from asteroid import Asteroid, Mine
from constants import (
    ASTEROID_MIN_RADIUS,
    MINE_BLAST_RADIUS,
    MINE_MARKER_COLOR,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import draw_hud
from main import FloatingText, detonate_mine, handle_collisions, mint_destructions
from particles import Particle
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)
# Keep the logger out of the repo tree: the proof's own events land here.
logger._STATE_LOG_PATH = os.path.join(OUT, "mines_state.jsonl")
logger._EVENT_LOG_PATH = os.path.join(OUT, "mines_events.jsonl")

random.seed(11)  # deterministic debris

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
particles = pygame.sprite.Group()
floaters = pygame.sprite.Group()
Particle.containers = (particles, updatable)
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
FloatingText.containers = (floaters, updatable)

player = Player(100, 660)  # far outside every blast in this script
player.invulnerability_timer = 0.0
game = Game(player, asteroids, shots, powerups,
            save_path=os.path.join(OUT, "mines_save.json"))
economy = Economy(save_path=os.path.join(OUT, "mines_economy.json"))

MINE_SPOT = pygame.Vector2(640, 360)
NEIGHBOR_SPOT = pygame.Vector2(700, 360)   # 60 px: inside the blast
RIM_SPOT = pygame.Vector2(640 + MINE_BLAST_RADIUS + 80, 360)  # beyond the rim
PLAIN_SPOT = pygame.Vector2(860, 360)      # an unarmed rock, for contrast

DARK_PHASE = 0.25   # the marker's dark half (period 1/3 s)
LIT_PHASE = 0.0


def render_frame():
    """One main-loop render: entities, then fx (particles, floats), HUD last."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    for each in particles:
        each.draw(screen)
    for each in floaters:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)


# --- Scenario A: the armed rock, marker in its dark half -----------------------
mine = Mine(MINE_SPOT.x, MINE_SPOT.y, ASTEROID_MIN_RADIUS)
neighbor = Asteroid(NEIGHBOR_SPOT.x, NEIGHBOR_SPOT.y, ASTEROID_MIN_RADIUS * 2)
outside = Asteroid(RIM_SPOT.x, RIM_SPOT.y, ASTEROID_MIN_RADIUS)
plain = Asteroid(PLAIN_SPOT.x, PLAIN_SPOT.y, ASTEROID_MIN_RADIUS * 2)
mine.blink_clock = DARK_PHASE

render_frame()
mine_hull = screen.get_at((int(MINE_SPOT.x), int(MINE_SPOT.y)))
plain_center = screen.get_at((int(PLAIN_SPOT.x), int(PLAIN_SPOT.y)))
assert (mine_hull.r, mine_hull.g, mine_hull.b) == (44, 40, 62), \
    "the mine's dark filled hull must read at its center"
assert (plain_center.r, plain_center.g, plain_center.b) == PALETTE["paper"], \
    "a plain rock is outline-only: paper at its center"
pygame.image.save(screen, f"{OUT}/mine_armed_dark.png")

# --- Scenario B: the same mine, marker in the lit half -------------------------
mine.blink_clock = LIT_PHASE
render_frame()
marker = screen.get_at((int(MINE_SPOT.x), int(MINE_SPOT.y)))
assert (marker.r, marker.g, marker.b) == MINE_MARKER_COLOR, \
    "the danger marker blinks hostile red at the hull's center"
pygame.image.save(screen, f"{OUT}/mine_marker_lit.png")

# --- Scenario C: a shot kills the mine — the blast pays inside the rim ---------
prev = set(asteroids)
Shot(MINE_SPOT.x, MINE_SPOT.y)

handle_collisions(asteroids, shots, player, game, powerups)

assert not mine.alive(), "the shot killed the mine"
assert not neighbor.alive(), "the blast split the neighbor inside the rim"
assert outside.alive(), "the rock beyond the rim is untouched"
assert plain.alive(), "an unarmed rock inside the rim still pays (any body)"
children = [rock for rock in asteroids
            if rock not in (mine, neighbor, outside, plain)]
assert len(children) == 2 and all(not isinstance(c, Mine) for c in children), \
    "the neighbor splits into two plain children — no baby mines"

for _ in range(6):  # let the debris cloud spread a frame's worth
    for particle in list(updatable):
        particle.update(1 / 60)
assert len(particles) > 0, "the detonation renders a blast debris cloud"

paid = mint_destructions(prev, asteroids, economy, game.stats)
wrecks = [wreck for wreck, _ in paid]
assert mine in wrecks and neighbor in wrecks, "both kills mint via the diff"
assert not any(wreck.despawned for wreck in wrecks)
assert economy.credits == sum(payout for _, payout in paid) == 100 + 50, \
    "the one destruction→mint path paid the mine and the neighbor exactly once"
assert game.score == 100, "blast victims are combo-free: only the mine's shot kill pays points"
assert game.lives == 3, "the ship far outside the rim is unharmed"

events = [json.loads(line) for line in open(logger._EVENT_LOG_PATH)]
detonations = [event for event in events if event["type"] == "mine_detonated"]
assert len(detonations) == 1 and detonations[0]["victims"] == 1, \
    "the detonation logged one event naming its one victim (the neighbor)"

render_frame()
pygame.image.save(screen, f"{OUT}/mine_detonation.png")

print("mine evidence saved:",
      sorted(f for f in os.listdir(OUT) if f.startswith("mine")))
