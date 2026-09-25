"""Boss-wave evidence (capstone): the fifth-wave boss wears its layered-
armor rings, flashes on a landed shot, reads through a top-center HP bar,
and pays the capstone payoff — one guaranteed chaos-table drop plus the
ordinary destruction-diff mint.

Follows the proof_mines pattern — a bounded scripted session under SDL
dummy drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives
the real paths (maybe_boss_wave's spawner with the mode-scaled drift, the
sweep's shot-kill site, the drop tables, mint_destructions):

- boss_rings_bar.png     the boss at full HP: the multi-ring armor look
                         apart from a big rock, the hostile-red HP bar
                         full across the top, the drift armed
- boss_hit_flash.png     after two landed shots: the warm-white flash ring
                         riding the hull's outside, the HP bar visibly
                         shorter from the right
- boss_defeat_drop.png   the killing blow: the drop pickup drifting at the
                         death site under the debris, the +300 pts popup

The run asserts the ring/flash/HP-bar pixels, the drift's mode scaling,
the exactly-one-drop spawn (boss=True on its event), the one-diff mint
(the boss pays what any large rock pays), and the boss_spawned /
boss_hit / boss_defeated events, so a failing claim fails the script.
The paths themselves are pinned in tests/test_boss.py.
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
from asteroid import Asteroid, Boss, boss_tier
from asteroidfield import AsteroidField
from constants import (
    BOSS_BAR_FILL_COLOR,
    BOSS_BAR_TRACK_COLOR,
    BOSS_BAR_WIDTH,
    BOSS_BAR_Y,
    BOSS_DRIFT_SPEED,
    BOSS_RING_FRACTIONS,
    DIFFICULTY_TABLE,
    LINE_WIDTH,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import draw_boss_bar, draw_hud, points_for
from main import (
    FloatingText,
    handle_collisions,
    maybe_boss_wave,
    mint_destructions,
)
from particles import Particle
from player import Player
from powerups import BUFF_TYPES, PowerUp, PowerUpType
from shot import Shot

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)
# Keep the logger out of the repo tree: the proof's own events land here.
logger._STATE_LOG_PATH = os.path.join(OUT, "boss_state.jsonl")
logger._EVENT_LOG_PATH = os.path.join(OUT, "boss_events.jsonl")
# The logger appends across runs — start this evidence session's logs
# clean so the event counts below read only this script's own session.
for log_path in (logger._STATE_LOG_PATH, logger._EVENT_LOG_PATH):
    with open(log_path, "w"):
        pass

random.seed(11)  # deterministic debris and drop rolls

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
updatable, drawable, asteroids, shots, powerups = (pygame.sprite.Group() for _ in range(5))
particles = pygame.sprite.Group()
floaters = pygame.sprite.Group()
Particle.containers = (particles, updatable)
Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
PowerUp.containers = (powerups, updatable, drawable)
FloatingText.containers = (floaters, updatable)
AsteroidField.containers = updatable  # update-only: the field never draws

player = Player(100, 660)  # out of the fight: the drop must survive the sweep
player.invulnerability_timer = 0.0
game = Game(player, asteroids, shots, powerups,
            save_path=os.path.join(OUT, "boss_save.json"))
economy = Economy(save_path=os.path.join(OUT, "boss_economy.json"))
field = AsteroidField(game)


def render_frame(live_boss=None):
    """One main-loop render: entities, fx (particles, floats), HUD, HP bar."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    for each in particles:
        each.draw(screen)
    for each in floaters:
        each.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave)
    if live_boss is not None:
        draw_boss_bar(screen, live_boss)


# --- Scenario A: the boss fields its wave — rings, HP bar, drift -----------------
game.wave = 5
field.start_wave()
maybe_boss_wave(game, field)
boss = list(asteroids)[0]
assert isinstance(boss, Boss) and boss_tier(5) == 1, "wave 5 fields the tier-1 boss"
expected_drift = BOSS_DRIFT_SPEED * DIFFICULTY_TABLE["normal"]["speed_mult"]
assert boss.velocity.length() == expected_drift, "the mode-scaled drift armed"
print(f"boss drift {boss.velocity.length():.1f} px/s "
      f"(mode normal speed_mult {DIFFICULTY_TABLE['normal']['speed_mult']})")

render_frame(boss)
center = boss.position
ring_outer, ring_inner = BOSS_RING_FRACTIONS
# Probe mid-stroke: pygame's circle outline renders just inside its
# nominal radius (the draw scanline shows the stroke at [r-LW, r-1]).
outer_r, inner_r = int(boss.radius * ring_outer), int(boss.radius * ring_inner)
ring_probe = (int(center.x + outer_r - LINE_WIDTH // 2), int(center.y))
inner_probe = (int(center.x + inner_r - LINE_WIDTH // 2), int(center.y))
assert screen.get_at(ring_probe)[:3] == PALETTE["fringe_r"], \
    "the outer armor ring draws in the hostile red that owns the HP bar"
assert screen.get_at(inner_probe)[:3] == PALETTE["fringe_r"], \
    "the inner armor ring draws concentric inside it"
bar_x = (SCREEN_WIDTH - BOSS_BAR_WIDTH) / 2
fill_probe = (int(bar_x + 50), BOSS_BAR_Y + 4)
assert screen.get_at(fill_probe)[:3] == BOSS_BAR_FILL_COLOR, \
    "the HP bar's fill spans the full pool at max HP"
full_end = (int(bar_x + BOSS_BAR_WIDTH - 8), BOSS_BAR_Y + 4)
assert screen.get_at(full_end)[:3] == BOSS_BAR_FILL_COLOR, \
    "a full pool covers the whole track — no track shows at max HP"
pygame.image.save(screen, f"{OUT}/boss_rings_bar.png")


# --- Scenario B: landed shots flash the hull and drain the bar -------------------
boss.take_hit()
boss.take_hit()
assert boss.hp == boss.max_hp - 2

render_frame(boss)
flash_probe = (int(center.x + boss.radius + LINE_WIDTH), int(center.y))
assert screen.get_at(flash_probe)[:3] == PALETTE["hud_ink"], \
    "the landed shot's flash ring rides the hull's outside in warm white"
shrunk_fill = (int(bar_x + BOSS_BAR_WIDTH * ((boss.hp / boss.max_hp)) - 8), BOSS_BAR_Y + 4)
assert screen.get_at(shrunk_fill)[:3] == BOSS_BAR_FILL_COLOR, \
    "the fill still covers the drained pool's fraction"
beyond_fill = (int(bar_x + BOSS_BAR_WIDTH - 8), BOSS_BAR_Y + 4)
assert screen.get_at(beyond_fill)[:3] == BOSS_BAR_TRACK_COLOR, \
    "the drained right end reads as track, not fill"
pygame.image.save(screen, f"{OUT}/boss_hit_flash.png")

for _ in range(12):  # a blink's worth of sim time: the flash decays away
    boss.update(1 / 60)
assert boss.hit_flash == 0.0, "the flash lands exactly at zero"

# --- Scenario C: the killing blow pays the capstone payoff -----------------------
prev = set(asteroids)
boss.hp = 1
Shot(center.x, center.y)

handle_collisions(asteroids, shots, player, game, powerups)

assert not boss.alive(), "the killing blow emptied the pool"
assert game.score == 300, "the kill paid BOSS_POINTS through register_kill"
assert len(powerups) == 1, "the death guaranteed exactly one drop"
dropped = list(powerups)[0]
assert dropped.kind in BUFF_TYPES + (PowerUpType.MYSTERY,), \
    "the drop came from the ordinary chaos tables"
assert (dropped.position - center).length() <= boss.radius + 40, \
    "the prize lingers at the boss's death site"

paid = mint_destructions(prev, asteroids, economy, game.stats, wave=game.wave)
assert paid == [(boss, points_for(boss.radius))], \
    "the one destruction→mint path paid the boss what any large rock pays"
assert economy.credits == points_for(boss.radius)

FloatingText(center.x, center.y - 24, points_for(boss.radius),
             label="+pts", color=PALETTE["hud_ink"])
for _ in range(6):  # spread the death debris a frame's worth
    for particle in list(updatable):
        particle.update(1 / 60)
render_frame()
assert 0 < dropped.position.x < SCREEN_WIDTH and 0 < dropped.position.y < SCREEN_HEIGHT, \
    "the prize drifts on-screen at the death site"
pygame.image.save(screen, f"{OUT}/boss_defeat_drop.png")

events = [json.loads(line) for line in open(logger._EVENT_LOG_PATH)]
kinds = [event["type"] for event in events]
assert kinds.count("boss_spawned") == 1, "the spawner logged the spawn once"
assert kinds.count("boss_hit") == 3, "every landed shot logged a hit"
assert kinds.count("boss_defeated") == 1, "the mint pass logged the defeat"
spawns = [event for event in events if event["type"] == "powerup_spawned"]
assert len(spawns) == 1 and spawns[0]["boss"] is True, \
    "the guaranteed drop's event marks the payoff source"

print("boss evidence saved:",
      sorted(f for f in os.listdir(OUT) if f.startswith("boss")))
