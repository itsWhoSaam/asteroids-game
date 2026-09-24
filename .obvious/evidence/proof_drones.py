"""Drones evidence: bounded headless run through the real boot path — a
crafted save with a stale idle_last_seen loads through the Economy loader,
the offline grant is claimed once, and turret markers orbit the ship firing
real Shots. Captures PNGs to /tmp/obv-evidence/: the banner bright at boot,
gone after its fade, turrets and shots in live play."""

import json
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")

import pygame

from constants import (
    DRONE_FIRE_INTERVAL_S,
    OFFLINE_BANNER_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from asteroid import Asteroid
from asteroidfield import AsteroidField
from drones import DroneBay, OfflineBanner, drone_dps
from economy import Economy
from game import Game
from hud import draw_hud
from logger import log_event
from main import draw_credits, handle_collisions
from player import Player
from shop import Shop
from shot import Shot

os.makedirs("/tmp/obv-evidence", exist_ok=True)

# A stale save the real loader path reads: drone level 3, last seen 2 h ago.
SAVE = "game_save.json"
stale_seen = time.time() - 2 * 3600
with open(SAVE, "w") as f:
    json.dump(
        {
            "high_score": 4200,
            "idle_credits": 200.0,
            "idle_levels": {"nanoblade": 0, "fire_rate": 0, "income": 0, "drone": 3},
            "idle_last_seen": stale_seen,
        },
        f,
    )

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
clock = pygame.time.Clock()

updatable = pygame.sprite.Group()
drawable = pygame.sprite.Group()
asteroids = pygame.sprite.Group()
shots = pygame.sprite.Group()

Asteroid.containers = (asteroids, updatable, drawable)
Shot.containers = (shots, updatable, drawable)
AsteroidField.containers = updatable
asteroid_field = AsteroidField()

Player.containers = (updatable, drawable)
player1 = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player1, asteroids, shots)
economy = Economy()
shop = Shop(economy, player1)
drones = DroneBay(economy)
drones.sync()  # main() syncs on the first update; do it up front for the assert

# The boot grant, exactly as main() claims it — capped, half rate.
grant = economy.claim_offline(drone_dps(economy.levels["drone"]))
offline_banner = OfflineBanner(grant)
if offline_banner.amount > 0:
    log_event("offline_earnings", amount=grant)

# The grant math is the spec formula: dps × ~2 h × OFFLINE_RATE (under the
# cap; a few ms of clock drift between stamp and claim is tolerated).
grant_expected = drone_dps(3) * 7200 * 0.5
assert len(drones.turrets) == 3, f"expected 3 turrets, got {len(drones.turrets)}"
assert abs(grant - grant_expected) < 1.0
assert economy.credits == 200.0 + grant

frames = 0
while frames < 300:  # 5 s: banner (4 s) fully fades by the last capture
    dt = clock.tick(60) / 1000
    updatable.update(dt)
    drones.update(dt, player1, asteroids, shots)
    handle_collisions(asteroids, shots, player1, game)

    screen.fill("black")
    for each in drawable:
        each.draw(screen)
    drones.draw(screen, player1)

    draw_hud(screen, game.score, lives=game.lives)
    draw_credits(screen, economy.credits)
    offline_banner.update(dt)
    offline_banner.draw(screen)
    shop.draw_panel(screen)
    pygame.display.flip()

    if frames in (30, 100, 299):
        pygame.image.save(screen, f"/tmp/obv-evidence/drones_{frames}.png")
    frames += 1

assert offline_banner.lifetime <= 0  # the fade completed

print(
    f"ran {frames} frames, drones={len(drones.turrets)} "
    f"(level {economy.levels['drone']}), grant={grant:.1f}cr, "
    f"credits={economy.credits:.1f}, banner_seconds={OFFLINE_BANNER_SECONDS}, "
    f"first_fire_at={DRONE_FIRE_INTERVAL_S * 0.5:.2f}s, asteroids={len(asteroids)}"
)
