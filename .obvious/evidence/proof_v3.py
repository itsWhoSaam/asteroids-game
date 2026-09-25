"""Visual V3 evidence: the comic background — halftone dot-screen and radial
action lines — pre-rendered once and blitted at screen level.

The populated frame with the overlay over it, a 6x zoom where the dot grid
and the inner-radius line boundary read clearly, and the worst-case
composite (now including the background blit, as main composes it) timed
against the blueprint's <=12ms budget. Self-checks pin the overlay variant
(uniform surface alpha), the halftone grid, and the action-line geometry.

Run: uv run python .obvious/evidence/proof_v3.py
Out: /tmp/obv-evidence/v3_background.png, v3_halftone_zoom.png,
     v3_composite_budget.png
"""

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")

import pygame

import hud
from asteroid import Asteroid
from comicfx import (
    ACTION_LINE_INNER_RADIUS,
    BACKGROUND_ALPHA,
    HALFTONE_SPACING,
    build_background,
)
from constants import PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH
from particles import Particle, burst
from player import Player
from powerups import PowerUp, PowerUpType
from shot import Shot

OUT_DIR = "/tmp/obv-evidence"
COMPOSITE_BUDGET_MS = 12.0


def build_world():
    """The same populated frame V1/V2 evidence used: ship + shield, one rock
    per tier, shots, two pickups, sparks — everything the restyle touches."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)
    Player.containers = (updatable, drawable)

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.activate_powerup(PowerUpType.SHIELD)
    Asteroid(220, 200, 60)   # large -> violet
    Asteroid(1000, 180, 40)  # medium -> pink
    Asteroid(300, 520, 20)   # small -> light pink
    Asteroid(950, 500, 20)
    shot = Shot(640, 420)
    shot.velocity = pygame.Vector2(0, -400)
    PowerUp(420, 380, PowerUpType.RAPID)
    PowerUp(880, 300, PowerUpType.TRIPLE)
    burst(pygame.Vector2(760, 420), 60)  # debris cloud over a wreck site
    for spark in list(particles):
        spark.update(0.35)  # spread the cloud before the static frame

    return drawable, player


def render_frame(screen, drawable, background):
    """Main's V3 composition exactly: paper fill, one flat draw pass into
    the world surface, world blit, background blit, HUD on top."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    world.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(world)

    screen.fill(PALETTE["paper"])
    screen.blit(world, (0, 0))
    screen.blit(background, (0, 0))
    hud.draw_hud(screen, 1250, lives=3, wave=2, muted=True)


def assert_overlay_variant(overlay):
    """The overlay is the measured cheap variant: opaque pixels faded by
    uniform surface alpha (per-pixel SRCALPHA would blend per pixel and
    cost ~0.25ms more per frame). get_alpha() returning the value is the
    pin — on a per-pixel surface surface-alpha is unused and reads None."""
    assert overlay.get_alpha() == BACKGROUND_ALPHA, (
        f"overlay alpha {overlay.get_alpha()} != BACKGROUND_ALPHA {BACKGROUND_ALPHA}"
    )
    print(f"self-check ok: opaque overlay faded by uniform alpha {BACKGROUND_ALPHA}")


def assert_grid_and_lines(overlay):
    """The grid and the lines, pinned as pixels: dot centers show the
    halftone swatch with paper between them, a line runs along the +x ray
    past the inner radius, and the disk inside it stays clean."""
    dot = (HALFTONE_SPACING, 0)
    gap = (HALFTONE_SPACING // 2, 0)
    assert overlay.get_at(dot) == (*PALETTE["halftone"], 255), "no halftone dot"
    assert overlay.get_at(gap) == (*PALETTE["paper"], 255), "gap is not paper"

    center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
    on_ray = [
        overlay.get_at((center[0] + offset, center[1]))
        for offset in range(ACTION_LINE_INNER_RADIUS + 2, ACTION_LINE_INNER_RADIUS + 40)
    ]
    assert (*PALETTE["action_line"], 255) in on_ray, "no action line on the +x ray"

    inner = ACTION_LINE_INNER_RADIUS - 20
    for dx in range(-inner, inner + 1, 4):
        for dy in range(-inner, inner + 1, 4):
            if dx * dx + dy * dy > inner * inner:
                continue  # sample the disk, not the box
            pixel = overlay.get_at((center[0] + dx, center[1] + dy))
            assert pixel in (
                (*PALETTE["paper"], 255),
                (*PALETTE["halftone"], 255),
            ), f"line leaked inside the inner radius at {(dx, dy)}"
    print("self-check ok: halftone grid on cells, lines start past the inner radius")


def save_halftone_zoom(background, filename):
    """6x zoom of a patch around the +x action line, where the dot grid and
    the line read at pixel scale."""
    patch_size = 160
    x = SCREEN_WIDTH // 2 + ACTION_LINE_INNER_RADIUS - patch_size // 2
    y = SCREEN_HEIGHT // 2 - patch_size // 2
    patch = pygame.Surface((patch_size, patch_size))
    patch.blit(background, (0, 0), (x, y, patch_size, patch_size))
    zoom = pygame.transform.scale_by(patch, 6)
    pygame.image.save(zoom, filename)


def build_worst_case():
    """The blueprint's worst-case counts: 60 rocks, 70 shots, 30 pickups,
    500 sparks with spread ages."""
    dummy = pygame.sprite.Group()
    Asteroid.containers = (dummy,)
    Shot.containers = (dummy,)
    PowerUp.containers = (dummy,)
    Particle.containers = (dummy,)

    rocks = [
        Asteroid(40 + (i % 60) * 20, 100 + (i // 60) * 240, 60 - (i % 3) * 20)
        for i in range(60)
    ]
    shots = [Shot(40 + i * 17.5, 650 - (i % 4) * 10) for i in range(70)]
    pickups = [PowerUp(40 + i * 40, 690, PowerUpType.RAPID) for i in range(30)]
    sparks = []
    for i in range(500):
        spark = Particle(640, 360, pygame.Vector2(0, 1).rotate(i) * 100)
        spark.age = (i % 10) * 0.05  # spread ages so spark sizes vary
        sparks.append(spark)
    return rocks, shots, pickups, sparks


def draw_composite(surface, rocks, shots, pickups, sparks):
    surface.fill(PALETTE["paper"])
    for rock in rocks:
        rock.draw(surface)
    for shot in shots:
        shot.draw(surface)
    for pickup in pickups:
        pickup.draw(surface)
    for spark in sparks:
        spark.draw(surface)


def assert_composite_budget(screen, background, rocks, shots, pickups, sparks):
    """Worst-case composite — now with the background blit inside the loop,
    since main pays it every frame — holds the blueprint's <=12ms budget."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    frames = 60
    start = time.perf_counter()
    for _ in range(frames):
        draw_composite(world, rocks, shots, pickups, sparks)
        screen.blit(world, (0, 0))
        screen.blit(background, (0, 0))
    elapsed_ms = (time.perf_counter() - start) * 1000 / frames

    draw_composite(screen, rocks, shots, pickups, sparks)
    screen.blit(background, (0, 0))
    pygame.image.save(screen, f"{OUT_DIR}/v3_composite_budget.png")

    assert elapsed_ms <= COMPOSITE_BUDGET_MS, (
        f"composite draw+blit took {elapsed_ms:.2f}ms, budget {COMPOSITE_BUDGET_MS}ms"
    )
    print(
        f"self-check ok: worst-case composite draw+blit (incl. background) = "
        f"{elapsed_ms:.2f}ms/frame (budget {COMPOSITE_BUDGET_MS}ms)"
    )


def main():
    pygame.init()
    os.makedirs(OUT_DIR, exist_ok=True)
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    start = time.perf_counter()
    background = build_background(SCREEN_WIDTH, SCREEN_HEIGHT)
    print(f"background pre-render (one-time): {(time.perf_counter() - start) * 1000:.1f}ms")

    drawable, _ = build_world()
    render_frame(screen, drawable, background)
    pygame.image.save(screen, f"{OUT_DIR}/v3_background.png")
    save_halftone_zoom(background, f"{OUT_DIR}/v3_halftone_zoom.png")

    assert_overlay_variant(background)
    assert_grid_and_lines(background)

    rocks, shots, pickups, sparks = build_worst_case()
    assert_composite_budget(screen, background, rocks, shots, pickups, sparks)

    print(
        f"wrote {OUT_DIR}/v3_background.png, {OUT_DIR}/v3_halftone_zoom.png, "
        f"{OUT_DIR}/v3_composite_budget.png"
    )


if __name__ == "__main__":
    main()
