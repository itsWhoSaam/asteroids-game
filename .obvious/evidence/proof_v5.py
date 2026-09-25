"""Visual V5 evidence: the comic HUD family — score/lives/wave panel,
game-over caption panels, the tilted wave banner with its quantized fade,
and the bare-ink audio tags.

A populated frame composed through main.render_world — the real pass
split with the V5 HUD panel top-left and a live banner mid-fade over the
scene; the game-over overlay's three caption panels; a five-tile banner
fade strip (full ink to paper-blend); the MUTED + VOL corner in its
deliberately unpanelled ink. Self-checks pin the plate/dot panel pixels,
the untouched MUTED slot when unmuted, per-tile fade dimming, the tilted
glyph cache, and the worst-case composite budget with the banner inside
it.

Run: uv run python .obvious/evidence/proof_v5.py
Out: /tmp/obv-evidence/v5_hud.png, v5_game_over.png, v5_banner_fade.png,
     v5_audio_tags.png
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
    Burst,
    build_background_layers,
    burst_word,
    clear_burst_texts,
    spawn_burst,
)
from constants import (
    GAME_OVER_LINE_STEP,
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

PAPER = PALETTE["paper"]
PANEL_YELLOW = PALETTE["hud_panel"]
PANEL_DOT = PALETTE["hud_panel_dot"]
PANEL_FAMILY = (PANEL_YELLOW, PANEL_DOT)


class FakeGame:
    """The run-state slice render_world reads for the HUD."""

    score = 1250
    lives = 2
    wave = 2
    muted = False


def build_world():
    """The populated V5 hero frame: the V1–V3 cast plus the HUD panel and
    a live POW! so the panel demonstrably rides the real composition."""
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
    Asteroid(220, 200, 60)
    Asteroid(1000, 180, 40)
    Asteroid(300, 520, 20)

    spawn_burst(pygame.Vector2(220, 200), 60, burst_word(60))
    burst(pygame.Vector2(220, 200), 60)
    for spark in list(particles):
        spark.update(0.15)

    shot = Shot(640, 420)
    shot.velocity = pygame.Vector2(0, -400)
    PowerUp(420, 380, PowerUpType.RAPID)

    return entities, fx


def banner_at(timer):
    """A banner frame at a specific fade timer, composited on fresh paper
    the way the game composites each frame."""
    tile = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    tile.fill(PAPER)
    banner = hud.WaveBanner(duration=2.0)
    banner.show(1)
    banner.timer = timer
    banner.draw(tile)
    return tile


def save(surface, name):
    path = os.path.join(OUT_DIR, name)
    pygame.image.save(surface, path)
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    outputs = []
    comicfx._text_cache.clear()  # fresh caches, like a new process
    comicfx._rotated_cache.clear()
    hud.clear_panels()

    # --- 1. hero frame: populated world + HUD panel + banner mid-fade
    entities, fx = build_world()
    background = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    render_world(screen, world, background, entities, fx, (0, 0), FakeGame())

    banner = hud.WaveBanner(duration=2.0)
    banner.show(2)
    banner.timer = 1.4  # mid-fade: tilted letters, plate partially dimmed
    banner.draw(screen)
    outputs.append(save(screen, "v5_hud.png"))

    # the panel shows in its left padding (plate or one of its dots)...
    panel_pixel = screen.get_at((12, 40))[:3]
    assert panel_pixel in PANEL_FAMILY, panel_pixel
    # ...the unmuted corner stays bare paper — the MUTED tripwire slot
    assert screen.get_at((SCREEN_WIDTH - 2, 2))[:3] == PAPER

    # --- 2. game-over: every caption line on its own panel
    screen.fill(PAPER)
    hud.clear_panels()
    hud.draw_game_over(screen, FakeGame.score, new_high=True)
    outputs.append(save(screen, "v5_game_over.png"))

    lines = ["Game over — score 1250", "New high score!", "press R to restart, Q to quit"]
    step = GAME_OVER_LINE_STEP
    top = SCREEN_HEIGHT / 2 - len(lines) * step / 2
    for row, text in enumerate(lines):
        width = hud.game_over_font().size(text)[0]
        point = (round(SCREEN_WIDTH / 2 - width / 2) - 6, round(top + (row + 0.5) * step))
        assert screen.get_at(point)[:3] in PANEL_FAMILY, (text, point)

    # --- 3. the banner fade strip: five quantized steps, fresh paper each
    comicfx._text_cache.clear()
    comicfx._rotated_cache.clear()
    hud.clear_panels()
    tiles = [banner_at(t) for t in (2.0, 1.5, 1.0, 0.5, 0.12)]
    tile_h = SCREEN_HEIGHT // 5
    strip = pygame.Surface((SCREEN_WIDTH, tile_h * 5))
    for i, tile in enumerate(tiles):
        strip.blit(pygame.transform.scale(tile, (SCREEN_WIDTH, tile_h)), (0, i * tile_h))
    outputs.append(save(strip, "v5_banner_fade.png"))

    # the plate dims monotonically as the timer spends: distance from the
    # paper backdrop shrinks each step (black ink brightens as it fades)
    rect = banner._panel.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3))
    plate = (rect.left + 7, rect.centery)

    def from_paper(pixel):
        return sum((c - p) ** 2 for c, p in zip(pixel[:3], PAPER))

    plate_samples = [from_paper(tile.get_at(plate)) for tile in tiles]
    assert plate_samples[0] == from_paper(PANEL_YELLOW) or plate_samples[0] > 400000
    assert all(a > b for a, b in zip(plate_samples, plate_samples[1:]))
    assert len(comicfx._rotated_cache) > 0  # tilted glyphs came from the cache

    cache_size = len(comicfx._rotated_cache)
    for _ in range(3):
        banner_at(1.0)  # identical redraws never grow the cache
    assert len(comicfx._rotated_cache) == cache_size

    # --- 4. audio tags: bare ink in the corner, no panel behind them
    screen.fill(PAPER)
    hud.clear_panels()
    hud.draw_hud(screen, FakeGame.score, muted=True, volume=70)
    outputs.append(save(screen, "v5_audio_tags.png"))
    assert screen.get_at((SCREEN_WIDTH - 2, 2))[:3] == PAPER  # slot stays unpanelled

    # --- 5. composite budget: the worst-case frame with banner and HUD
    for extra in range(60):
        Asteroid(200, 200, 20)
    for extra in range(70):
        Shot(100 + extra, 100)
    for extra in range(500):
        Particle(640, 360, pygame.Vector2(0, -100))
    start = time.perf_counter()
    frames = 60
    for _ in range(frames):
        render_world(screen, world, background, entities, fx, (0, 0), FakeGame())
        banner.draw(screen)
        pygame.display.flip()
    mean_ms = (time.perf_counter() - start) * 1000 / frames
    assert mean_ms < COMPOSITE_BUDGET_MS, mean_ms

    print(f"V5 evidence OK — composite {mean_ms:.2f}ms/frame (budget {COMPOSITE_BUDGET_MS}ms)")
    for path in outputs:
        print(f"  {path}")


if __name__ == "__main__":
    main()
