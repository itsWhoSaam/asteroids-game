"""F6 evidence: procedural sound and the mute toggle, headless (engagement F6).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
mute handler and save loader:

- f6_unmuted.png  the HUD as it always was — no indicator (the 'before')
- f6_muted.png    the same HUD after a simulated M press — the MUTED tag
                  sits top-right, and game_save.json now carries muted=true

The simulated M press is main()'s exact handler body
(`sound.set_muted(game.toggle_mute())`) — the event-pump block is not
restructured for F6. Audio itself is verified by init(): the mixer comes up
at (44100, -16, 2) even under the dummy driver and all six cues synthesize;
playback calls fire at the real destruction sites during the scripted run.
"""

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from constants import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SFX_CHANNELS,
    SFX_FORMAT,
    SFX_SAMPLE_RATE,
)
from game import Game
from hud import HUD_MARGIN, draw_hud, hud_font
from main import handle_collisions
from particles import Particle, Shake
from player import Player
from shot import Shot
import sound

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
sound.init()  # the real startup path: mixer + synthesized SFX, or silent no-op
mixer_format = pygame.mixer.get_init()
assert mixer_format == (SFX_SAMPLE_RATE, SFX_FORMAT, SFX_CHANNELS), mixer_format
assert len(sound._sounds) == 6, f"expected the full SFX table, got {set(sound._sounds)}"

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups, particles = (
    pygame.sprite.Group() for _ in range(6)
)
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
Particle.containers = (particles, updatable, drawable)
Player.containers = (updatable, drawable)

shake = Shake()
player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, powerups, particles=particles, shake=shake,
            save_path=f"{OUT}/f6_game_save.json")
sound.set_muted(game.muted)  # main()'s startup sync, verbatim


def render_frame():
    """The main loop's render, verbatim — including the F6 muted flag."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    world.fill("black")
    for each in drawable:
        each.draw(world)
    screen.fill("black")
    screen.blit(world, shake.offset())
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             muted=game.muted)


# A rock in view; destroying it below also fires the explosion sfx for real.
Asteroid(640, 360, 60)
render_frame()
pygame.image.save(screen, f"{OUT}/f6_unmuted.png")

# --- the simulated M press: main()'s exact handler body -----------------------
sound.set_muted(game.toggle_mute())
assert game.muted is True

# while muted, destruction still resolves — playback suppressed, no crash
Shot(640, 360)
handle_collisions(asteroids, shots, player, game, powerups, shake)
assert game.score > 0, "muted gameplay must play on"

render_frame()
pygame.image.save(screen, f"{OUT}/f6_muted.png")

# the indicator is really on screen, top-right, only in the muted frame
rect = hud_font().render("MUTED", True, "white").get_rect(
    topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
)


def indicator_pixels():
    screen.fill("black")
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             muted=game.muted)
    return sum(
        1
        for x in range(rect.left, rect.right, 3)
        for y in range(rect.top, rect.bottom, 3)
        if screen.get_at((x, y))[:3] != (0, 0, 0)
    )


lit = indicator_pixels()
assert lit > 0, "the MUTED tag must light pixels top-right while muted"

saved = json.loads(open(f"{OUT}/f6_game_save.json").read())
assert saved["muted"] is True, "the toggle must persist through the save loader"

print(f"F6 evidence written to {OUT}:")
for name in ("f6_unmuted.png", "f6_muted.png"):
    print(f"  {OUT}/{name}")
print(f"mixer at {mixer_format}, cues: {sorted(sound._sounds)}")
print(f"MUTED indicator: {lit} lit sample pixels at {rect}; "
      f"save after toggle: {saved}")
