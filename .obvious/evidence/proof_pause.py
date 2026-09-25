"""Pause evidence: the frozen frame + PAUSED overlay, headless (Tier 1 pause).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/:

- pause_before.png        live mid-run frame: world, HUD, no overlay
- pause_after.png         the same frame frozen under the dimmed PAUSED overlay
- frames/f%03d.png        a short before -> pause -> resume sequence
                          (ffmpeg assembles it into the interaction WebM)

Self-checks assert the pause contract on the pixels and the world: the dim
darkens the corner to the expected blend, the world holds perfectly still
across paused steps, resume moves it again, and paused/resumed events land
in the log. Exit code 0 only when every check passes.
"""

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from asteroidfield import AsteroidField
from comicfx import build_background
from constants import PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH
from drones import DroneBay
from economy import Economy
from game import Game
from hud import WaveBanner, draw_hud, draw_pause
from main import update_world
from particles import Shake
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
FRAMES = f"{OUT}/pause-frames"
os.makedirs(FRAMES, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots = (pygame.sprite.Group() for _ in range(4))
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
AsteroidField.containers = updatable
Player.containers = (updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, save_path="/tmp/obv-evidence/game_save.json")
field = AsteroidField(game)
economy = Economy(save_path="/tmp/obv-evidence/idle_save.json")
drones = DroneBay(economy)
banner = WaveBanner()
shake = Shake()
background = build_background(SCREEN_WIDTH, SCREEN_HEIGHT)

# A believable mid-run scene: some score, real rocks around the ship.
# CircleShape leaves velocity at zero — the field normally assigns it on
# spawn, so the script sets drift speeds explicitly (the tracked rock must
# move on resume for the freeze/resume check below to mean anything).
game.add_score(3250)
for x, y, r, vx, vy in (
    (280, 180, 55, 60, -25),
    (980, 240, 40, -45, 30),
    (720, 560, 30, -30, -40),
    (180, 520, 25, 35, 20),
):
    rock = Asteroid(x, y, r)
    rock.velocity = pygame.Vector2(vx, vy)


def render_frame():
    """One faithful main-loop frame: shaken world, texture, HUD, overlays."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    world.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(world)
    screen.fill(PALETTE["paper"])
    screen.blit(world, shake.offset())
    screen.blit(background, (0, 0))
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             muted=game.muted, volume=game.volume)


def capture(name):
    pygame.image.save(screen, name)


def corner():
    return screen.get_at((SCREEN_WIDTH - 20, SCREEN_HEIGHT - 20))[:3]


def snap_sequence():
    """Save the numbered frames ffmpeg turns into the interaction WebM."""
    seq = ["live", "live", "pause", "pause", "pause", "pause",
           "live", "live", "pause", "pause"]
    for i, state in enumerate(seq):
        if state == "pause" and not game.paused:
            game.toggle_pause()
        if state == "live" and game.paused:
            game.toggle_pause()
        render_frame()
        if game.paused:
            draw_pause(screen)
        capture(f"{FRAMES}/f{i:03d}.png")


# --- Scenario A: live frame (before) ---
render_frame()
capture(f"{OUT}/pause_before.png")
before_corner = corner()
before_rock_pos = pygame.Vector2(
    next(a for a in asteroids if a.radius == 55).position
)

# --- Scenario B: paused frame (after) ---
assert game.toggle_pause() is True
render_frame()
draw_pause(screen)
capture(f"{OUT}/pause_after.png")
after_corner = corner()

# The dim must darken the corner to exactly the surface-alpha blend, and
# the PAUSED sheet must be the only thing that changed the frame there.
share = 160 / 255
dim = (12, 10, 34)
expected = tuple(round(dim[i] * share + before_corner[i] * (1 - share)) for i in range(3))
assert after_corner != before_corner, "corner unchanged — the dim sheet never drew"
assert all(abs(after_corner[i] - expected[i]) <= 2 for i in range(3)), (
    f"corner {after_corner} is not the dim blend over {before_corner}"
)

# --- The freeze itself: paused steps move nothing, resume does ---
for _ in range(3):
    update_world(updatable, drones, asteroids, shots, player, game,
                 [], shake, field, banner, economy, 1 / 60)
paused_step_pos = pygame.Vector2(next(a for a in asteroids if a.radius == 55).position)
assert paused_step_pos == before_rock_pos, "a paused step moved the world"

assert game.toggle_pause() is True  # resume
update_world(updatable, drones, asteroids, shots, player, game,
             [], shake, field, banner, economy, 1 / 60)
resumed_pos = pygame.Vector2(next(a for a in asteroids if a.radius == 55).position)
assert resumed_pos != before_rock_pos, "resume left the world frozen"

# --- Event log: the freeze and the resume were recorded ---
types = set()
with open("game_events.jsonl") as fh:
    for line in fh:
        types.add(json.loads(line)["type"])
assert "paused" in types and "resumed" in types, f"missing pause events in {types}"

# --- The interaction sequence (before -> pause -> resume -> pause) ---
game.paused = False
snap_sequence()

print("PROOF PAUSE: all checks passed")
print(f"  corner blend   {before_corner} -> {after_corner} (expected ~{expected})")
print(f"  freeze         rock held at {tuple(round(v, 2) for v in before_rock_pos)} across paused steps")
print(f"  resume         rock moved to {tuple(round(v, 2) for v in resumed_pos)}")
print(f"  events         paused + resumed logged")
print(f"  artifacts      {OUT}/pause_before.png, {OUT}/pause_after.png, {FRAMES}/")
