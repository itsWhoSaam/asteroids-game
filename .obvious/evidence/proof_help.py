"""Help evidence: the keybind list over dimmed play, headless (Tier 1 help).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/:

- help_before.png         live mid-run frame: world, HUD, no overlay
- help_after.png          the same frame dimmed under the keybind list
- help_stacked.png        help up over the paused overlay (both dims)
- frames/f%03d.png        a closed -> open -> closed toggle sequence
                          (ffmpeg assembles it into the interaction WebM)

Self-checks assert the help contract on the pixels and the world: the dim
darkens the corner to the expected blend, the world keeps moving under the
list (help dims, it never freezes — pause is the freeze), and a second H
press closes it. Exit code 0 only when every check passes.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from asteroidfield import AsteroidField
from comicfx import build_background_layers
from constants import (
    HELP_LINE_STEP,
    HELP_TITLE_STEP,
    PAUSE_OVERLAY_DIM_ALPHA,
    PAUSE_OVERLAY_DIM_COLOR,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from drones import DroneBay
from economy import Economy
from game import Game
from hud import WaveBanner, draw_help, draw_pause, help_keymap
from main import render_world, update_world
from particles import Shake
from player import Player
from shot import Shot

OUT = "/tmp/obv-evidence"
FRAMES = f"{OUT}/help-frames"
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
background = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
fx_group = pygame.sprite.Group()  # bursts/particles pass — empty for this scene

# The help block must fit the screen: title + rows inside 720 px — the layout
# math draw_help uses, checked here so a rebalance can't silently overflow.
block_height = HELP_TITLE_STEP + len(help_keymap()) * HELP_LINE_STEP
assert block_height < SCREEN_HEIGHT, "help list overflows the screen"

world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))


def render_frame():
    """One faithful main-loop frame through the real V4 composition."""
    render_world(screen, world, background, drawable, fx_group,
                 shake.offset(), game)


def capture(name):
    pygame.image.save(screen, name)


def corner():
    return screen.get_at((SCREEN_WIDTH - 20, SCREEN_HEIGHT - 20))[:3]


# A believable mid-run scene: some score, real rocks around the ship.
# CircleShape leaves velocity at zero — the field normally assigns it on
# spawn, so the script sets drift speeds explicitly (the rock must move
# under the open list for the dims-not-freezes check below to mean anything).
game.add_score(3250)
for x, y, r, vx, vy in (
    (280, 180, 55, 60, -25),
    (980, 240, 40, -45, 30),
    (720, 560, 30, -30, -40),
    (180, 520, 25, 35, 20),
):
    rock = Asteroid(x, y, r)
    rock.velocity = pygame.Vector2(vx, vy)


# --- Scenario A: live frame, list closed (before) ---
render_frame()
capture(f"{OUT}/help_before.png")
before_corner = corner()
before_rock_pos = pygame.Vector2(
    next(a for a in asteroids if a.radius == 55).position
)

# --- Scenario B: the list up over the same play (after) ---
assert game.toggle_help() is True
render_frame()
draw_help(screen)
capture(f"{OUT}/help_after.png")
after_corner = corner()

# The dim must darken the corner to exactly the surface-alpha blend, and
# the help sheet must be the only thing that changed the frame there.
share = PAUSE_OVERLAY_DIM_ALPHA / 255
dim = PAUSE_OVERLAY_DIM_COLOR
expected = tuple(round(dim[i] * share + before_corner[i] * (1 - share)) for i in range(3))
assert after_corner != before_corner, "corner unchanged — the dim sheet never drew"
assert all(abs(after_corner[i] - expected[i]) <= 2 for i in range(3)), (
    f"corner {after_corner} is not the dim blend over {before_corner}"
)

# --- Help dims, it never freezes: a step still moves the world ---
update_world(updatable, drones, asteroids, shots, player, game,
             [], shake, field, banner, economy, 1 / 60)
open_pos = pygame.Vector2(next(a for a in asteroids if a.radius == 55).position)
assert open_pos != before_rock_pos, "help froze the world — that is pause's job"

# --- Second H press closes the list ---
assert game.toggle_help() is True
assert game.help_open is False

# --- Stacked: help up over the paused overlay renders both dims ---
assert game.toggle_pause() is True
assert game.toggle_help() is True
render_frame()
draw_pause(screen)
draw_help(screen)  # main's z-order: the list over the paused dim
capture(f"{OUT}/help_stacked.png")
stacked_corner = corner()
double_share = share * share  # two independent alpha blits compound
double_expected = tuple(
    round(dim[i] * share + expected[i] * (1 - share)) for i in range(3)
)
assert stacked_corner != after_corner, "the second dim never stacked"
assert all(abs(stacked_corner[i] - double_expected[i]) <= 2 for i in range(3)), (
    f"stacked corner {stacked_corner} is not the double blend over {expected}"
)
# Unwind: resume, close help.
game.toggle_help()
game.toggle_pause()
assert game.help_open is False and game.paused is False


def snap_sequence():
    """Save the numbered frames ffmpeg turns into the toggle WebM:
    closed -> open -> closed, two seconds each way."""
    seq = ["closed", "closed", "open", "open", "open", "open",
           "closed", "closed"]
    for i, state in enumerate(seq):
        if state == "open" and not game.help_open:
            game.toggle_help()
        if state == "closed" and game.help_open:
            game.toggle_help()
        render_frame()
        if game.help_open:
            draw_help(screen)
        capture(f"{FRAMES}/f{i:03d}.png")


# --- The interaction sequence (closed -> open -> closed) ---
snap_sequence()

print("PROOF HELP: all checks passed")
print(f"  corner blend   {before_corner} -> {after_corner} (expected ~{expected})")
print(f"  dims-not-freezes  rock moved {tuple(round(v, 2) for v in before_rock_pos)} -> {tuple(round(v, 2) for v in open_pos)} with the list up")
print(f"  stacked        {after_corner} -> {stacked_corner} (expected ~{double_expected})")
print(f"  rows           {len(help_keymap())} keybind rows, block {block_height:.0f}px of {SCREEN_HEIGHT}px")
print(f"  artifacts      {OUT}/help_before.png, {OUT}/help_after.png, {OUT}/help_stacked.png, {FRAMES}/")
