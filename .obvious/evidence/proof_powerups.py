"""Insane-powerups evidence: bounded headless run driving the real systems.

Captures to /tmp/obv-evidence/:
  - powerups_strip.png   — the shop panel with the powerup strip (before)
  - powerups_active.png  — green active-effect countdown (gold rush + overdrive)
  - nuke_before.png      — a populated field seconds before the nuke
  - nuke_after.png       — the cleared field, NUKE! label, credits minted

The loop replicates main()'s pump and mint steps — powerup keys route
through the Shop/Economy seams, destruction mints through the same
frame-to-frame diff the live game polls. Asserts the nuke single-payout
invariant end to end: exactly one credit per rock on screen, the field
empty, and the use counts persisted.
"""
import os, sys
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")
os.makedirs("/tmp/obv-evidence", exist_ok=True)

import pygame
from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import SCREEN_WIDTH, SCREEN_HEIGHT, POWERUPS
from economy import Economy
from game import Game
from hud import draw_hud, points_for
from main import FloatingText, destroyed_asteroids, draw_credits, nuke_field
from player import Player
from shop import Shop
import sound

pygame.init()
sound.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
clock = pygame.time.Clock()

updatable, drawable = pygame.sprite.Group(), pygame.sprite.Group()
asteroids, shots, powerups, particles = (pygame.sprite.Group() for _ in range(4))
floaters = pygame.sprite.Group()
Asteroid.containers = (asteroids, updatable, drawable)
AsteroidField.containers = updatable
Player.containers = (updatable, drawable)
FloatingText.containers = (floaters, updatable, drawable)

player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
game = Game(player, asteroids, shots, powerups, particles=particles)
field = AsteroidField(game)
economy = Economy()
shop = Shop(economy, player)
economy.credits = 2600  # playtest stipend: affordable strip + a nuke

frames = 0
prev_asteroids = set(asteroids)
credits_before_nuke = None
expected_nuke_payout = None
while frames < 300:  # 5 simulated seconds
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            sys.exit(0)
    dt = clock.tick(60) / 1000

    if frames == 30:  # strip visible with live escalating prices
        pygame.image.save(screen, "/tmp/obv-evidence/powerups_strip.png")
    if frames == 60:  # activate gold rush + overdrive through the ledger
        assert shop.handle_powerup_key(pygame.K_7) == "gold_rush"
        assert shop.handle_powerup_key(pygame.K_9) == "overdrive"
        FloatingText(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3, 0,
                     label=f"{POWERUPS['gold_rush']['title'].upper()}!",
                     color=(120, 255, 180))
    if frames == 90:  # countdown indicator glowing above the panel
        pygame.image.save(screen, "/tmp/obv-evidence/powerups_active.png")
    if frames == 120:  # field populated — the moment before the nuke
        pygame.image.save(screen, "/tmp/obv-evidence/nuke_before.png")
        expected_nuke_payout = (
            sum(points_for(a.radius) for a in asteroids) * economy.gold_rush_mult()
        )
        assert shop.handle_powerup_key(pygame.K_8) == "nuke"
        # Baseline AFTER the purchase: the delta below must be the mint alone.
        credits_before_nuke = economy.credits
        # The KEYDOWN branch's destruction step — plain splits, the loop's
        # diff below is what pays.
        nuke_field(asteroids)
        FloatingText(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3, 0,
                     label="NUKE!", color=(120, 255, 180))
    if frames == 126 and credits_before_nuke is not None:
        # Single-payout invariant, end to end: every pre-nuke rock paid once.
        assert len(asteroids) == 0, "the nuke must clear the field"
        assert economy.powerup_uses["nuke"] == 1
        minted = economy.credits - credits_before_nuke
        assert abs(minted - expected_nuke_payout) < 1e-6, f"{minted} != {expected_nuke_payout}"
    if frames == 150:  # NUKE! float still rising over the cleared field
        pygame.image.save(screen, "/tmp/obv-evidence/nuke_after.png")

    economy.tick_powerups(dt)
    Asteroid.speed_scale = economy.chrono_scale()
    updatable.update(dt)

    # main()'s mint step: the destruction diff pays each wreck once.
    for wreck in destroyed_asteroids(prev_asteroids, asteroids):
        payout = economy.mint(wreck.radius)
        FloatingText(wreck.position.x, wreck.position.y, payout)
    prev_asteroids = set(asteroids)

    screen.fill("black")
    for d in drawable:
        d.draw(screen)
    draw_hud(screen, game.score, lives=game.lives, wave=game.wave, muted=game.muted)
    draw_credits(screen, economy.credits)
    shop.draw_panel(screen)
    shop.draw_powerups(screen)
    for f in list(floaters):
        f.update(dt)
    pygame.display.flip()
    frames += 1

print(f"frames={frames} expected_nuke_payout={expected_nuke_payout}")
print(f"credits {credits_before_nuke} -> {economy.credits}")
print(f"powerup_uses={economy.powerup_uses} timers={dict(economy.powerup_timers)}")
print("evidence: 4 PNGs in /tmp/obv-evidence/")
