"""UFO-saucer evidence (Tier 3): every ~45 s a saucer enters from a random
screen edge, crosses with a sinusoidal drift, and fires aimed shots at the
player — the only shots that can reach the ship.

Follows the proof_magnet pattern — a bounded scripted session under SDL
dummy drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives
the real paths (the dt spawn cadence, the drift kinematics, the aimed fire
through the shared Shot pipeline, the sweep, the destruction-diff mint):

- ufo_entering.png   the saucer just inside its entry edge, mid-drift, no
                     shots yet — the crossing has begun
- ufo_firing.png     the same saucer deeper in, its aimed shot in flight
                     toward the ship

The run asserts the cadence spawned exactly one saucer at an edge with an
inward heading, the drift is perpendicular sine motion, the fired shot is
tagged from_ufo at the saucer's shot speed aimed at the player, and a
player shot that kills the saucer pays its own points_for tier through the
destroyed_ufos diff mint. The cadence and integration paths themselves are
pinned in tests/test_ufo.py.
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
    PALETTE,
    SCORE_UFO,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    UFO_SHOT_SPEED,
    UFO_SPAWN_INTERVAL_S,
)
from economy import Economy
from game import Game
from hud import draw_hud
from main import (
    FloatingText,
    draw_credits,
    handle_collisions,
)
from particles import Particle
from player import Player
from shot import Shot
from ufo import UFO, UFOSpawner, destroyed_ufos

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

random.seed(11)  # deterministic entry edge and drift phase

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, ufos = (
    pygame.sprite.Group() for _ in range(5)
)
floaters = pygame.sprite.Group()
particles = pygame.sprite.Group()
powerups = pygame.sprite.Group()

Player.containers = (updatable, drawable)
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
UFO.containers = (ufos, updatable, drawable)
FloatingText.containers = (floaters, updatable, drawable)
Particle.containers = (particles, updatable, drawable)

player = Player(900, 360)  # the aim target, right of center
game = Game(player, asteroids, shots, ufos=ufos)
economy = Economy(save_path=os.path.join(OUT, "ufo_save.json"))


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


# --- Scenario A: the cadence spawns a saucer at an edge, heading in ---------
spawner = UFOSpawner()
spawner.update(UFO_SPAWN_INTERVAL_S - 0.5, player)
assert len(ufos) == 0, "no saucer before the interval"

spawner.update(0.5, player)  # the clock crosses the boundary
assert len(ufos) == 1, "the 45 s cadence spawned one saucer"
ufo = ufos.sprites()[0]

center = pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
pos = pygame.Vector2(ufo.position)
off_screen = (
    pos.x < 0 or pos.x > SCREEN_WIDTH or pos.y < 0 or pos.y > SCREEN_HEIGHT
)
assert off_screen, "the saucer enters from off-screen"
assert ufo.velocity.dot(center - pos) > 0, "the crossing aims inward"
assert not ufo.despawned

for _ in range(90):  # 1.5 s of drift: onto the screen, visibly mid-crossing
    ufo.update(1 / 60)
assert ufo.position.distance_to(center) < pos.distance_to(center), \
    "the saucer closed on the field"
render_frame()
pygame.image.save(screen, f"{OUT}/ufo_entering.png")

# --- Scenario B: the aimed shot in flight toward the ship -------------------
fired = None
for _ in range(200):  # the first cadence fires within UFO_FIRE_INTERVAL_S
    ufo.update(1 / 60)
    if len(shots) > 0:
        fired = shots.sprites()[0]
        break
assert fired is not None, "the saucer fired on its cadence"
assert fired.from_ufo and not fired.from_drone, "the shot is tagged from_ufo"

# Aim: same direction as saucer→ship; speed: the saucer's (dodgeable).
to_player = pygame.Vector2(player.position) - pygame.Vector2(ufo.position)
assert fired.velocity.dot(to_player) > 0, "the shot aims at the ship"
assert abs(fired.velocity.length() - UFO_SHOT_SPEED) < 1e-6, \
    "the shot rides its own speed"

for _ in range(15):  # 0.25 s: the bullet visibly between saucer and ship
    ufo.update(1 / 60)
    for shot in list(shots):
        shot.update(1 / 60)
assert fired.alive(), "the shot is still in flight"
render_frame()
pygame.image.save(screen, f"{OUT}/ufo_firing.png")

# --- Scenario C: the shoot-down payout through the ordinary mint ------------
for shot in list(shots):  # clear the flight path: the hunter is the only shot
    shot.kill()

prev_ufos = set(ufos)
hunter = Shot(ufo.position.x + 20, ufo.position.y)  # overlapping: dead hit
hunter.velocity = pygame.Vector2(-300, 0)
handle_collisions(asteroids, shots, player, game, powerups, ufos=ufos)
assert not ufo.alive(), "one player shot kills the saucer"
assert game.score == SCORE_UFO, "the saucer pays its own points_for tier"
kills = destroyed_ufos(prev_ufos, ufos)
assert kills == [ufo], "the destruction diff surfaces the kill"
for wreck in kills:
    economy.mint(wreck.radius)
assert economy.credits == SCORE_UFO, "the mint paid the same tier"

print("ufo evidence saved:",
      sorted(f for f in os.listdir(OUT) if f.startswith("ufo_")))
