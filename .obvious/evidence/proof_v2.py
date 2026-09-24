"""Visual V2 evidence: chromatic comic outlines, rendered headless.

The populated frame with the ink/fringe/fill stack live on the ship, the
shield ring, rocks, shots and pickups — plus a 4× ship close-up where the
red/cyan fringes read clearly. Particles stay outline-free sparks with the
spawn pop (the blueprint's exclusion). Self-checks pin the stack as pixels,
re-verify the ring-band tripwire on the inked ship, and time the worst-case
composite against the blueprint's ≤12ms budget.

Run: uv run python .obvious/evidence/proof_v2.py
Out: /tmp/obv-evidence/v2_outlines.png, v2_ship_closeup.png,
     v2_composite_budget.png
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
from comicfx import FRINGE_PX, chromatic_circle
from constants import (
    LINE_WIDTH,
    PALETTE,
    PLAYER_RADIUS,
    POWERUP_SHIELD_RING_GAP,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from particles import Particle, burst
from player import Player
from powerups import PowerUp, PowerUpType
from shot import Shot

OUT_DIR = "/tmp/obv-evidence"
COMPOSITE_BUDGET_MS = 12.0


def build_world():
    """The same populated frame V1's evidence used: everything the restyle
    touches — ship + shield, one rock per tier, shots, two pickups, sparks."""
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
    Asteroid(220, 200, 60)   # large → violet
    Asteroid(1000, 180, 40)  # medium → pink
    Asteroid(300, 520, 20)   # small → light pink
    Asteroid(950, 500, 20)
    shot = Shot(640, 420)
    shot.velocity = pygame.Vector2(0, -400)
    PowerUp(420, 380, PowerUpType.RAPID)
    PowerUp(880, 300, PowerUpType.TRIPLE)
    burst(pygame.Vector2(760, 420), 60)  # debris cloud over a wreck site
    for spark in list(particles):
        spark.update(0.35)  # spread the cloud before the static frame

    return drawable, player


def render_frame(screen, drawable):
    """Main's composition for the V2 surfaces: paper fill, one flat draw
    pass (the explicit fx-layer passes are a later visual PR), HUD on top."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    hud.draw_hud(screen, 1250, lives=3, wave=2, muted=True)


def assert_probe_stack(screen):
    """The ink/fringe/fill stack, pinned as pixels on a probe circle."""
    paper = (*PALETTE["paper"], 255)
    red = (*PALETTE["fringe_r"], 255)
    cyan = (*PALETTE["fringe_c"], 255)
    ink = (0, 0, 0, 255)
    color = (*PALETTE["shot"], 255)
    center = (320, 240)
    radius = 40

    screen.fill(PALETTE["paper"])
    chromatic_circle(screen, PALETTE["shot"], center, radius, LINE_WIDTH)

    def ray(offset, sign=1, vertical=False):
        x, y = center
        if vertical:
            return screen.get_at((x, y + sign * offset))
        return screen.get_at((x + sign * offset, y))

    # the colored stroke still lands on the hull band (bottom pole, clear
    # of the horizontal fringes), fringes flank it one per side, ink closes
    # the poles
    assert any(ray(o, sign=-1, vertical=True) == color
               for o in range(radius - LINE_WIDTH, radius)), "no fill stroke"
    assert any(ray(o, sign=-1) == red
               for o in range(radius + 1, radius + FRINGE_PX + 2)), "no red fringe"
    assert any(ray(o) == cyan
               for o in range(radius + 1, radius + FRINGE_PX + 2)), "no cyan fringe"
    assert any(ray(o, sign=-1, vertical=True) == ink
               for o in range(radius + 1, radius + LINE_WIDTH + FRINGE_PX + 1)), "no ink"
    print("self-check ok: fill stroke, red/cyan fringes, and black ink all present")


def assert_ring_band_clear(screen):
    """The ring-band tripwire on the inked ship: unshielded, the outline
    (hull + fringes + ink) never paints the band where the shield ring
    would sit — 25–32px from center."""
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    screen.fill(PALETTE["paper"])
    player.draw(screen)

    ring = PLAYER_RADIUS + POWERUP_SHIELD_RING_GAP
    for side in (1, -1):
        for offset in range(ring - 3, ring + 5):
            pixel = screen.get_at(
                (int(SCREEN_WIDTH / 2) + side * offset, int(SCREEN_HEIGHT / 2))
            )
            assert pixel == (*PALETTE["paper"], 255), (
                f"ship outline leaked into the ring band at offset {side * offset}"
            )
    print("self-check ok: unshielded ship outline stays clear of the 25-32px ring band")


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


def assert_composite_budget(screen, rocks, shots, pickups, sparks):
    """Worst-case composite draw+blit holds the blueprint's ≤12ms budget."""
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    frames = 60
    start = time.perf_counter()
    for _ in range(frames):
        draw_composite(world, rocks, shots, pickups, sparks)
        screen.blit(world, (0, 0))
    elapsed_ms = (time.perf_counter() - start) * 1000 / frames

    draw_composite(screen, rocks, shots, pickups, sparks)
    pygame.image.save(screen, f"{OUT_DIR}/v2_composite_budget.png")

    assert elapsed_ms <= COMPOSITE_BUDGET_MS, (
        f"composite draw+blit took {elapsed_ms:.2f}ms, budget {COMPOSITE_BUDGET_MS}ms"
    )
    print(
        f"self-check ok: worst-case composite draw+blit = {elapsed_ms:.2f}ms/frame "
        f"(budget {COMPOSITE_BUDGET_MS}ms)"
    )


def save_ship_closeup(screen, filename):
    """4× zoom on the shielded ship — the only place the fringes are big
    enough to read in a PNG."""
    box = pygame.Rect(
        int(SCREEN_WIDTH / 2) - 48, int(SCREEN_HEIGHT / 2) - 48, 96, 96
    )
    closeup = pygame.transform.scale_by(screen.subsurface(box).copy(), 4)
    pygame.image.save(closeup, filename)


def main():
    pygame.init()
    os.makedirs(OUT_DIR, exist_ok=True)
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    drawable, _ = build_world()

    render_frame(screen, drawable)
    pygame.image.save(screen, f"{OUT_DIR}/v2_outlines.png")
    save_ship_closeup(screen, f"{OUT_DIR}/v2_ship_closeup.png")

    assert_probe_stack(screen)
    assert_ring_band_clear(screen)

    rocks, shots, pickups, sparks = build_worst_case()
    assert_composite_budget(screen, rocks, shots, pickups, sparks)

    print(
        f"wrote {OUT_DIR}/v2_outlines.png, {OUT_DIR}/v2_ship_closeup.png, "
        f"{OUT_DIR}/v2_composite_budget.png"
    )


if __name__ == "__main__":
    main()
