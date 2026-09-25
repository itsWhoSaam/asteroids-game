"""Low-lives warning evidence: the pulsing lives line + edge vignette,
headless (UX wave).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/:

- low_lives_before.png    healthy frame at 2 lives: resting HUD, no vignette
- low_lives_rest.png      the 1-life frame with the line at rest size
- low_lives_after.png     the 1-life frame at the pulse peak + vignette
- frames/f%03d.png        one full pulse breath at 1 life (ffmpeg assembles
                          it into the interaction WebM)

Self-checks assert the feature contract on the pixels and the state: the
vignette darkens the corner to the expected blend only at 1 life, the
pulsing lives line paints strictly more ink at peak than at rest, the
game-over screen shows no vignette, and the gate re-derives cleanly after
a restart. Exit code 0 only when every check passes.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from comicfx import build_background_layers
from constants import (
    HUD_LINE_STEP,
    HUD_MARGIN,
    LOW_LIVES_PULSE_SECONDS,
    LOW_LIVES_VIGNETTE_COLOR,
    LOW_LIVES_VIGNETTE_MAX_ALPHA,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from hud import LowLivesWarning, draw_game_over
from main import render_world
from player import Player

OUT = "/tmp/obv-evidence"
FRAMES = f"{OUT}/low-lives-frames"
os.makedirs(FRAMES, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
drawable = pygame.sprite.Group()
Player.containers = (drawable,)
Asteroid.containers = (drawable,)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, pygame.sprite.Group(), pygame.sprite.Group(),
            save_path=f"{OUT}/game_save.json")
game.add_score(8620)
game.wave = 4
for x, y, r in ((280, 180, 55), (980, 240, 40), (720, 560, 30), (180, 520, 25)):
    Asteroid(x, y, r)

warning = LowLivesWarning()
background = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))


def render_frame():
    """One faithful main-loop frame through the real V4 composition."""
    render_world(screen, world, background, drawable, [], (0, 0), game, warning)


def capture(name):
    pygame.image.save(screen, name)


def corner():
    return screen.get_at((2, 2))[:3]


def lives_row_ink():
    """Text-ink pixels in the lives-line slot (row 1) — the pulse meter.

    Counts PALETTE["hud_ink"] exactly (the warm-white glyph cores), not
    non-background: the V5 comic panel plates the whole slot, so a
    !=paper count saturates at the panel's coverage and cannot see the
    text at all."""
    strip = pygame.Surface((260, 40))
    strip.blit(screen, (0, 0),
               pygame.Rect(HUD_MARGIN, HUD_MARGIN + HUD_LINE_STEP, 260, 40))
    return sum(
        1
        for x in range(strip.get_width())
        for y in range(strip.get_height())
        if strip.get_at((x, y))[:3] == (255, 247, 230)
    )


# --- Scenario A: healthy frame at 2 lives (before) ---
game.lives = 2
warning.update(0.0, game.lives, game.state)
assert warning.active is False
render_frame()
capture(f"{OUT}/low_lives_before.png")
before_corner = corner()
assert before_corner == (23, 18, 58), "no vignette may print at 2 lives"

# --- Scenario B: the 1-life frame, line at rest ---
game.lives = 1
warning.update(0.0, game.lives, game.state)
assert warning.active is True
render_frame()
capture(f"{OUT}/low_lives_rest.png")
rest_corner = corner()
rest_ink = lives_row_ink()
share = LOW_LIVES_VIGNETTE_MAX_ALPHA / 255
expected = tuple(
    round(LOW_LIVES_VIGNETTE_COLOR[i] * share + before_corner[i] * (1 - share))
    for i in range(3)
)
assert rest_corner != before_corner, "the vignette never printed at 1 life"
assert all(abs(rest_corner[i] - expected[i]) <= 2 for i in range(3)), (
    f"corner {rest_corner} is not the vignette blend over {before_corner}"
)

# --- Scenario C: the pulse peak — the line breathes larger ---
warning.phase = LOW_LIVES_PULSE_SECONDS / 2  # the cosine peak
render_frame()
capture(f"{OUT}/low_lives_after.png")
peak_ink = lives_row_ink()
assert peak_ink > rest_ink, (
    f"peak ink {peak_ink} must exceed rest ink {rest_ink} — the pulse is invisible"
)

# --- Scenario D: game over clears the treatment ---
for _ in range(1):
    game.player_hit()
assert game.state == "game_over"
warning.update(0.0, game.lives, game.state)
assert warning.active is False
render_frame()
draw_game_over(screen, game.score, new_high=game.new_high)
capture(f"{OUT}/low_lives_game_over.png")
over_corner = corner()
assert over_corner == before_corner, (
    "the vignette must not survive onto the game-over screen"
)

# --- Scenario E: restart re-arms from a clean gate ---
game.restart()
warning.update(0.0, game.lives, game.state)
assert warning.active is False

# --- The interaction sequence: one full breath at 1 life ---
game.lives = 1
STEPS = 10
for i in range(STEPS):
    warning.update(LOW_LIVES_PULSE_SECONDS / STEPS, game.lives, game.state)
    render_frame()
    capture(f"{FRAMES}/f{i:03d}.png")

print("PROOF LOW-LIVES: all checks passed")
print(f"  corner blend   {before_corner} -> {rest_corner} (expected ~{expected})")
print(f"  pulse ink      rest {rest_ink} -> peak {peak_ink} px")
print(f"  game over      vignette cleared (corner {over_corner})")
print(f"  artifacts      {OUT}/low_lives_before.png, low_lives_rest.png, "
      f"low_lives_after.png, low_lives_game_over.png, {FRAMES}/")
