"""Near-miss-graze-bonus evidence (Tier 3): dodging a rock's fast close pass —
outside the collision radius, inside the graze band — pays a small score bonus
with its own white pts popup, once per pair per cooldown, never while the ship
is invulnerable.

Follows the proof_magnet pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
paths (the sweep's graze pass, the pure graze_pays gate, the Game score seam,
the FloatingText dt-timer template):

- graze_before.png       the rock well beyond the band: no popup, score 0
- graze_after.png        the same rock riding the band's middle: the white
                         '+25 pts' popup a head above the rock, score 25
- graze_cooldown.png     an immediate re-pass, rock still in the band: no
                         second popup — the per-pair cooldown holds the band
- graze_invulnerable.png a fresh rock in the band of a blinking ship: no
                         popup — the respawn grace suppresses the bonus

The run asserts the score awards, the popup label/color/site, the cooldown
block, the invulnerability gate, and a zero credit ledger before each save,
so a failing claim fails the script. The gates themselves are pinned in
tests/test_graze.py.
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
    ASTEROID_MIN_RADIUS,
    GRAZE_BAND_PX,
    GRAZE_POINTS,
    PALETTE,
    PLAYER_INVULNERABILITY_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import draw_hud
from main import (
    FloatingText,
    draw_credits,
    graze_pays,
    handle_collisions,
)
from player import Player

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

random.seed(13)  # deterministic crack seeds — the scene is staged anyway

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
floaters = pygame.sprite.Group()
Asteroid.containers = (asteroids, updatable, drawable)
FloatingText.containers = (floaters, updatable, drawable)
Player.containers = (updatable, drawable)

player = Player(420, 420)  # the dodger
game = Game(player, asteroids, shots, powerups)
economy = Economy(save_path=os.path.join(OUT, "graze_save.json"))

ROCK_RADIUS = ASTEROID_MIN_RADIUS * 2
COLLISION = player.radius + ROCK_RADIUS  # the band's inner edge: a touch
FAST_PLAYER = (120.0, -20.0)
FAST_ROCK = 90.0


def render_frame():
    """One full main-loop render, minus the event pump."""
    screen.fill(PALETTE["paper"])
    for each in drawable:  # pass 2: entities
        each.draw(screen)
    for each in floaters:  # pass 3: fx — floating popups
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    draw_credits(screen, economy.credits)


def band_rock(inset, y_offset=0.0):
    """A rock riding the graze band `inset` px inside its outer edge."""
    rock = Asteroid(
        player.position.x + COLLISION + inset,
        player.position.y + y_offset,
        ROCK_RADIUS,
    )
    rock.velocity = pygame.Vector2(-FAST_ROCK, 0)  # crossing the hull's flank
    return rock


def pts_popups():
    return [f for f in floaters if f.label.endswith("pts")]


# --- Scene 1: the rock is a polite distance out — no band, no bonus ----------
far_rock = band_rock(inset=200.0)
player.velocity = pygame.Vector2(*FAST_PLAYER)
assert graze_pays(
    COLLISION + GRAZE_BAND_PX / 2,  # the band's middle — where scene 2 puts…
    COLLISION,                      # …the rock: this pair pays by construction
    player.velocity.length(), far_rock.velocity.length(),
) is True, "the staged pair pays by construction — the scene is honest"

handle_collisions(asteroids, shots, player, game, powerups)

assert game.score == 0, "beyond the band pays nothing"
assert not pts_popups(), "no popup without a paid graze"

render_frame()
pygame.image.save(screen, f"{OUT}/graze_before.png")

# --- Scene 2: the same rock now crosses the band — the dodge pays ------------
far_rock.position = pygame.Vector2(
    player.position.x + COLLISION + GRAZE_BAND_PX / 2, far_rock.position.y
)
popup_site = pygame.Vector2(far_rock.position)

handle_collisions(asteroids, shots, player, game, powerups)

assert game.score == GRAZE_POINTS, "the band pays the small score bonus"
popups = pts_popups()
assert len(popups) == 1, "exactly one pts popup for the paid graze"
assert popups[0].label == f"+{GRAZE_POINTS} pts"
assert popups[0].position.x == popup_site.x
assert popups[0].position.y == popup_site.y - 24.0, "a head above the rock"
assert economy.credits == 0.0, "score only — the credit ledger is untouched"

render_frame()
pygame.image.save(screen, f"{OUT}/graze_after.png")

# --- Scene 3: hovering — an immediate re-pass pays nothing -------------------
for floater in list(floaters):
    floater.kill()  # a clean frame: only a NEW popup would prove a re-pay
game.tick(1 / 60)  # one frame of sim time — the cooldown is still live

handle_collisions(asteroids, shots, player, game, powerups)

assert game.score == GRAZE_POINTS, "the per-pair cooldown blocks the re-graze"
assert not pts_popups(), "no second popup while the pair re-arms"

render_frame()
pygame.image.save(screen, f"{OUT}/graze_cooldown.png")

# --- Scene 4: the respawn blink suppresses the band --------------------------
# A fresh rock crosses the band of a blinking ship — the grace window pays
# nothing, so post-respawn hovering cannot farm the bonus.
blinker = band_rock(inset=GRAZE_BAND_PX / 2, y_offset=-60.0)
player.invulnerability_timer = PLAYER_INVULNERABILITY_SECONDS  # 2.0 s: visible

handle_collisions(asteroids, shots, player, game, powerups)

assert player.invulnerable and blinker.alive()
assert game.score == GRAZE_POINTS, "invulnerable passes never pay"
assert not pts_popups(), "no popup while the blink holds"
assert economy.credits == 0.0, "still score-only at the end"

render_frame()
pygame.image.save(screen, f"{OUT}/graze_invulnerable.png")

print("graze evidence saved:", sorted(
    name for name in os.listdir(OUT) if name.startswith("graze_")
))
