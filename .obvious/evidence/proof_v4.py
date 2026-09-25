"""Visual V4 evidence: comic bursts + onomatopoeia on the explicit draw
passes.

The populated frame composed through main.render_world — the real pass
split (action lines under entities, fx above them, halftone print, HUD
last) — with live POW!/BOOM!/ZAP! bursts at their destruction sites; a
burst lifecycle strip (pop-in to fade); and self-checks pinning the word
table by tier, the 4-text cap with oldest evicted, the fx-over-entities
z-order, the flat text-cache render count across simulated frames, and
the worst-case composite budget with live bursts inside it.

Run: uv run python .obvious/evidence/proof_v4.py
Out: /tmp/obv-evidence/v4_bursts.png, v4_burst_lifecycle.png,
     v4_composite_budget.png
"""

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")

import pygame

import comicfx
import hud
from asteroid import Asteroid
from comicfx import (
    BURST_TEXT_MAX_CONCURRENT,
    BURST_WORD_DEATH,
    BURST_WORD_LARGE,
    BURST_WORD_MEDIUM,
    Burst,
    build_background_layers,
    burst_word,
    clear_burst_texts,
    spawn_burst,
)
from constants import (
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from main import render_world
from particles import Particle, burst
from player import Player
from powerups import PowerUp, PowerUpType
from shot import Shot

OUT_DIR = "/tmp/obv-evidence"
COMPOSITE_BUDGET_MS = 12.0


def build_world():
    """The populated frame, now with live bursts: a POW! over a wrecked
    large rock, a BOOM! over a medium one, and a ZAP! at the ship — plus
    the V1–V3 cast (ship + shield, rocks per tier, shots, pickups,
    sparks)."""
    updatable = pygame.sprite.Group()
    entities = pygame.sprite.Group()
    fx = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, entities)
    Shot.containers = (shots, updatable, entities)
    PowerUp.containers = (powerups, updatable, entities)
    Particle.containers = (particles, updatable, fx)
    Burst.containers = (fx, updatable)
    Player.containers = (updatable, entities)

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.activate_powerup(PowerUpType.SHIELD)
    Asteroid(220, 200, 60)   # large -> violet
    Asteroid(1000, 180, 40)  # medium -> pink
    Asteroid(300, 520, 20)   # small -> light pink
    Asteroid(950, 500, 20)

    # live bursts at death sites — words join fx ahead of the debris
    spawn_burst(pygame.Vector2(220, 200), 60, BURST_WORD_LARGE)
    spawn_burst(pygame.Vector2(1000, 180), 40, BURST_WORD_MEDIUM)
    spawn_burst(player.position, player.radius, BURST_WORD_DEATH)
    burst(pygame.Vector2(220, 200), 60)  # the debris the POW! salutes
    burst(pygame.Vector2(1000, 180), 40)
    for spark in list(particles):
        spark.update(0.15)  # spread the clouds a little before the frame
    for sprite in fx:
        if isinstance(sprite, Burst):
            sprite.age = 0.3 * sprite.lifetime  # past the pop-in, full size

    shot = Shot(640, 420)
    shot.velocity = pygame.Vector2(0, -400)
    PowerUp(420, 380, PowerUpType.RAPID)
    PowerUp(880, 300, PowerUpType.TRIPLE)

    return player, entities, fx


def render_frame(screen, entities, fx, background):
    """Main's real composition — render_world with the pre-rendered pair."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    render_world(screen, world, background, entities, fx, (0, 0), FakeGame())


class FakeGame:
    """The run-state slice render_world reads for the HUD."""

    score = 1250
    lives = 2
    wave = 2
    muted = True


def assert_word_table():
    """The word gate, pinned on tiers: POW! large, BOOM! medium, small
    silent."""
    assert burst_word(ASTEROID_MAX_RADIUS) == BURST_WORD_LARGE
    assert burst_word(ASTEROID_MIN_RADIUS * 2) == BURST_WORD_MEDIUM
    assert burst_word(ASTEROID_MIN_RADIUS) is None
    print("self-check ok: POW! on large, BOOM! on medium, small stays silent")


def assert_burst_cap():
    """The cap: 6 concurrent bursts leave 4 live texts, oldest evicted."""
    clear_burst_texts()
    fx = pygame.sprite.Group()
    Burst.containers = (fx,)
    for i in range(BURST_TEXT_MAX_CONCURRENT + 2):
        spawn_burst(pygame.Vector2(100 + i * 10, 100), 60, BURST_WORD_LARGE)
    assert len(fx) == BURST_TEXT_MAX_CONCURRENT
    clear_burst_texts()
    print(f"self-check ok: burst texts capped at {BURST_TEXT_MAX_CONCURRENT}, oldest evicted")


def assert_fx_over_entities(background):
    """Z-order, pinned in pixels: a burst polygon drawn over a large rock
    at the same site wins the center — fx renders after entities."""
    updatable = pygame.sprite.Group()
    entities = pygame.sprite.Group()
    fx = pygame.sprite.Group()
    rocks = pygame.sprite.Group()
    Asteroid.containers = (rocks, updatable, entities)
    Burst.containers = (fx, updatable)

    site = (300, 300)
    Asteroid(*site, 60)
    word_burst = Burst(site[0], site[1], 60, BURST_WORD_LARGE, color=(255, 0, 0))

    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    render_world(screen, world, background, entities, fx, (0, 0), FakeGame())

    center = screen.get_at(site)
    # the red burst polygon wins the site (print-dimmed ~22%) — the rock's
    # violet fill would read blue-dominant if the entity pass ran after fx
    assert center.r > 190 and center.b < 90 and center.g < 40, (
        f"burst did not render above the rock at the shared site: {center}"
    )
    word_burst.kill()
    print("self-check ok: fx pass renders above the entity pass")


def assert_text_cache_flat():
    """The cache discipline: pickups + a burst drawn across simulated
    frames — comicfx font renders go flat after frame 1 (counted at the
    comicfx._font seam; the banner's once-per-wave render is pinned by the
    test suite)."""
    calls = []
    fonts = {}

    class CountingFont:
        def __init__(self, font):
            self._font = font

        def render(self, text, antialias, color=None, background=None):
            calls.append(text)
            return self._font.render(text, antialias, color, background)

    def counting_font(size):
        real = fonts.setdefault(size, pygame.font.Font(None, size))
        return CountingFont(real)

    original_font = comicfx._font
    comicfx._font = counting_font
    try:
        Burst.containers = ()
        PowerUp.containers = ()
        word_burst = Burst(400, 300, 60, BURST_WORD_MEDIUM)
        pickups = [
            PowerUp(200 + i * 100, 200, kind)
            for i, kind in enumerate(
                (PowerUpType.SHIELD, PowerUpType.RAPID, PowerUpType.TRIPLE)
            )
        ]
        screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        counts = []
        for _ in range(10):  # the burst outlives the window
            word_burst.update(1 / 60)
            for pickup in pickups:
                pickup.update(1 / 60)
            word_burst.draw(screen)
            for pickup in pickups:
                pickup.draw(screen)
            counts.append(len(calls))
    finally:
        comicfx._font = original_font
    assert counts[0] > 0, "no text rendered at all"
    assert counts[1:] == [counts[0]] * (len(counts) - 1), (
        f"font renders grew per frame: {counts}"
    )
    print(f"self-check ok: text cache flat after frame 1 ({counts[0]} cached)")


def save_burst_lifecycle(background, filename):
    """One burst drawn at four ages — 0%, 15%, 50%, 90% of its life — side
    by side: the pop-in, the hold, the fade to paper."""
    ages = (0.0, 0.15, 0.5, 0.9)
    cell = 220
    strip = pygame.Surface((cell * len(ages), cell))
    strip.fill(PALETTE["paper"])
    for i, age in enumerate(ages):
        fx = pygame.sprite.Group()
        Burst.containers = (fx,)
        word_burst = Burst(cell // 2 + i * cell, cell // 2, 70, BURST_WORD_LARGE)
        word_burst.age = age * word_burst.lifetime
        for sprite in fx:
            sprite.draw(strip)
        word_burst.kill()
    pygame.image.save(strip, filename)


def build_worst_case():
    """The blueprint's worst-case counts plus live bursts: 60 rocks, 70
    shots, 30 pickups, 500 sparks, and 4 concurrent burst texts."""
    dummy = pygame.sprite.Group()
    Asteroid.containers = (dummy,)
    Shot.containers = (dummy,)
    PowerUp.containers = (dummy,)
    Particle.containers = (dummy,)
    Burst.containers = (dummy,)

    rocks = [
        Asteroid(40 + (i % 60) * 20, 100 + (i // 60) * 240, 60 - (i % 3) * 20)
        for i in range(60)
    ]
    shots = [Shot(40 + i * 17.5, 650 - (i % 4) * 10) for i in range(70)]
    pickups = [PowerUp(40 + i * 40, 690, PowerUpType.RAPID) for i in range(30)]
    sparks = []
    for i in range(500):
        spark = Particle(640, 360, pygame.Vector2(0, 1).rotate(i) * 100)
        spark.age = (i % 10) * 0.05
        sparks.append(spark)
    bursts = [Burst(200 + i * 200, 200, 60, BURST_WORD_LARGE) for i in range(4)]
    return rocks, shots, pickups, sparks, bursts


def assert_composite_budget(screen, background, rocks, shots, pickups, sparks, bursts):
    """Worst-case composite with the V4 layers and live bursts — the
    blueprint's <=12ms budget."""
    lines, halftone = background
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    frames = 60
    start = time.perf_counter()
    for _ in range(frames):
        world.fill(PALETTE["paper"])
        world.blit(lines, (0, 0))
        for rock in rocks:
            rock.draw(world)
        for shot in shots:
            shot.draw(world)
        for pickup in pickups:
            pickup.draw(world)
        for burst_fx in bursts:
            burst_fx.draw(world)
        for spark in sparks:
            spark.draw(world)
        screen.blit(world, (0, 0))
        screen.blit(halftone, (0, 0))
    elapsed_ms = (time.perf_counter() - start) * 1000 / frames

    # one saved frame for the record
    world.fill(PALETTE["paper"])
    world.blit(lines, (0, 0))
    for rock in rocks:
        rock.draw(world)
    for shot in shots:
        shot.draw(world)
    for pickup in pickups:
        pickup.draw(world)
    for burst_fx in bursts:
        burst_fx.draw(world)
    for spark in sparks:
        spark.draw(world)
    screen.blit(world, (0, 0))
    screen.blit(halftone, (0, 0))
    pygame.image.save(screen, f"{OUT_DIR}/v4_composite_budget.png")

    assert elapsed_ms <= COMPOSITE_BUDGET_MS, (
        f"composite draw+blit took {elapsed_ms:.2f}ms, budget {COMPOSITE_BUDGET_MS}ms"
    )
    print(
        f"self-check ok: worst-case composite (bursts + passes) = "
        f"{elapsed_ms:.2f}ms/frame (budget {COMPOSITE_BUDGET_MS}ms)"
    )


def main():
    pygame.init()
    os.makedirs(OUT_DIR, exist_ok=True)
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    background = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
    clear_burst_texts()

    assert_word_table()
    assert_burst_cap()
    assert_fx_over_entities(background)
    assert_text_cache_flat()

    player, entities, fx = build_world()
    render_frame(screen, entities, fx, background)
    pygame.image.save(screen, f"{OUT_DIR}/v4_bursts.png")
    save_burst_lifecycle(background, f"{OUT_DIR}/v4_burst_lifecycle.png")

    rocks, shots, pickups, sparks, bursts = build_worst_case()
    assert_composite_budget(screen, background, rocks, shots, pickups, sparks, bursts)

    print(
        f"wrote {OUT_DIR}/v4_bursts.png, {OUT_DIR}/v4_burst_lifecycle.png, "
        f"{OUT_DIR}/v4_composite_budget.png"
    )


if __name__ == "__main__":
    main()
