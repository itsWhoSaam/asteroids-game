"""Insanity core evidence: combo, hit-stop, dash — headless.

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the real
paths (the sweep's shot branch, main.try_dash, the HitStop gate):

- insanity_combo_hud.png     COMBO x5 readout under the wave slot, mid-chain
- insanity_dash_cooling.png  DASH cooling slot right after the panic dash
- insanity_game_over.png     game-over overlay with the combo stat lines

Prints the run's insanity event trail and asserts the milestones landed:
combo_milestone, dash_used — plus a frozen hit-stop beat after the
multi-kill sweep.
"""

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid
from constants import ASTEROID_MIN_RADIUS, SCREEN_HEIGHT, SCREEN_WIDTH
from game import Game
from hud import draw_game_over, draw_hud
from main import HitStop, handle_collisions, try_dash
from particles import Particle, Shake
from player import Player
from powerups import PowerUp
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups, particles = (
    pygame.sprite.Group() for _ in range(6)
)
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
PowerUp.containers = (powerups, updatable, drawable)
Particle.containers = (particles, updatable, drawable)
Player.containers = (updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
shake = Shake()
game = Game(player, asteroids, shots, powerups, particles=particles, shake=shake)
hit_stop = HitStop()


def render(filename):
    """One full main-loop render with the insanity HUD slots."""
    screen.fill("black")
    for each in drawable:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
             combo=game.combo, dash_timer=player.dash_timer)
    pygame.image.save(screen, f"{OUT}/{filename}")


# --- Phase 1: a five-rock sweep — the chain reaches the first milestone ----
# Five large rocks, each with its own shot: one sweep kills all five, which
# is exactly the multi-kill frame the hit-stop multi beat prices.
spots = [(200, 200), (480, 160), (760, 200), (1040, 160), (640, 420)]
player.position.update((100, 660))  # out of every rock's reach: no player hit
for x, y in spots:
    Asteroid(x, y, ASTEROID_MIN_RADIUS * 3)
    Shot(x, y)
handle_collisions(asteroids, shots, player, game, powerups, shake,
                  hit_stop=hit_stop)

assert game.combo.chain == 5, "the sweep's shot kills must build the chain"
assert hit_stop.frozen and hit_stop.remaining > 0.05, (
    "a five-kill sweep must buy the multi beat"
)
print(f"hit-stop: frozen {hit_stop.remaining:.3f}s after a 5-kill sweep")
render("insanity_combo_hud.png")

# --- Phase 2: the dash — impulse, i-frames, the cooling slot ---------------
assert try_dash(player, game) is True
assert player.invulnerable and player.velocity.length() > 0
assert game.combo.chain == 0, "a successful dash breaks the chain"
render("insanity_dash_cooling.png")

# --- Phase 3: game over — the overlay reports the run's combo stats --------
game.lives = 1
game.player_hit()
assert game.state == "game_over"
screen.fill("black")
draw_game_over(screen, game.score, new_high=False,
               top_chain=game.combo.top, best_multiplier=game.combo.best_multiplier)
pygame.image.save(screen, f"{OUT}/insanity_game_over.png")

# --- Event trail ------------------------------------------------------------
events = []
with open("game_events.jsonl") as f:
    for line in f:
        events.append(json.loads(line))
kinds = {e["type"] for e in events}
insanity = sorted(kinds & {"combo_milestone", "combo_break", "dash_used"})
print("insanity events:", insanity)
assert "combo_milestone" in kinds, "the 5-chain must cross the first milestone"
assert "dash_used" in kinds, "the dash must log"

print("insanity core evidence written to", OUT)
