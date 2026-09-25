"""Master volume evidence: [ / ] stepping and the VOL tag, headless (UX wave).

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
step handler and save loader:

- volume_boot.png    the HUD at boot — VOL 100% top-right, no MUTED tag
- volume_stepped.png after three simulated [ presses — VOL 70% top-right
- volume_muted.png   after a simulated M press — VOL 70% MUTED side by side

The simulated [ press is main()'s exact handler body
(`sound.set_volume(game.step_volume(-1))`) — the event-pump block is not
restructured for the volume feature. Audio scaling is asserted on the real
synth-built cue: after playing at 70% the mixer Sound's gain is 0.7.
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
    SFX_SHOOT,
)
from game import Game
from hud import HUD_MARGIN, HUD_TAG_GAP, draw_hud, hud_font
from particles import Particle, Shake
from player import Player
import sound

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
sound.init()  # the real startup path: mixer + synthesized SFX, or silent no-op
assert sound.get_volume() == 100, "a fresh install boots at the default level"

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups, particles = (
    pygame.sprite.Group() for _ in range(6)
)
Asteroid.containers = (asteroids, updatable, drawable)
Particle.containers = (particles, updatable, drawable)
Player.containers = (updatable, drawable)

shake = Shake()
player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, powerups, particles=particles, shake=shake,
            save_path=f"{OUT}/volume_game_save.json")
sound.set_muted(game.muted)  # main()'s startup sync, verbatim
sound.set_volume(game.volume)  # main()'s startup sync, verbatim

Asteroid(640, 360, 60)  # a rock in view for composition


def render_frame():
    """The main loop's render, verbatim — including the volume kwarg."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    world.fill("black")
    for each in drawable:
        each.draw(world)
    screen.fill("black")
    screen.blit(world, shake.offset())
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             muted=game.muted, volume=game.volume)


def lit_pixels(rect):
    return sum(
        1
        for x in range(max(0, rect.left), rect.right, 3)
        for y in range(rect.top, rect.bottom, 3)
        if screen.get_at((x, y))[:3] != (0, 0, 0)
    )


def vol_rect(text="VOL 100%"):
    return hud_font().render(text, True, "white").get_rect(
        topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
    )


# --- boot frame: VOL 100% top-right, nothing muted ------------------------------
render_frame()
pygame.image.save(screen, f"{OUT}/volume_boot.png")
boot_vol = vol_rect()
assert lit_pixels(boot_vol) > 0, "the VOL 100% tag must light pixels top-right at boot"
# the beside slot (where MUTED sits once muted, left of VOL) is empty at boot
boot_beside = hud_font().render("MUTED", True, "white").get_rect(
    topright=(boot_vol.left - HUD_TAG_GAP, HUD_MARGIN)
)
assert lit_pixels(boot_beside) == 0, "no MUTED tag before the mute toggle"

# --- three simulated [ presses: main()'s exact handler body ---------------------
for _ in range(3):
    sound.set_volume(game.step_volume(-1))
assert game.volume == 70, f"three [ presses step 100 → 70, got {game.volume}"

render_frame()
pygame.image.save(screen, f"{OUT}/volume_stepped.png")
assert lit_pixels(vol_rect("VOL 70%")) > 0, "the stepped level must show as VOL 70%"

# the level really scales playback on the real synth-built cue (the mixer
# quantizes gain to 1/128 steps, so compare within one step)
sound.play(SFX_SHOOT)
gain = sound._sounds[SFX_SHOOT].get_volume()
assert abs(gain - 0.7) <= 1 / 128, f"playback gain must follow the level, got {gain}"

# --- a simulated M press: main()'s exact handler body ---------------------------
sound.set_muted(game.toggle_mute())
assert game.muted is True
assert game.volume == 70, "mute overrides audibly but preserves the level"

render_frame()
pygame.image.save(screen, f"{OUT}/volume_muted.png")
mut_rect = hud_font().render("MUTED", True, "white").get_rect(
    topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
)
beside_rect = hud_font().render("VOL 70%", True, "white").get_rect(
    topright=(SCREEN_WIDTH - HUD_MARGIN - mut_rect.width - HUD_TAG_GAP, HUD_MARGIN)
)
assert lit_pixels(mut_rect) > 0, "the MUTED tag keeps its F6 corner anchor"
assert lit_pixels(beside_rect) > 0, "the VOL tag renders beside MUTED while muted"

# --- persistence: the level rides the save merge --------------------------------
saved = json.loads(open(f"{OUT}/volume_game_save.json").read())
assert saved["volume"] == 70, "the stepped level must persist through the save loader"

print(f"Master-volume evidence written to {OUT}:")
for name in ("volume_boot.png", "volume_stepped.png", "volume_muted.png"):
    print(f"  {OUT}/{name}")
print(f"level after three [ presses: {game.volume}%, playback gain {gain}, "
      f"muted {game.muted}, save: {saved}")
