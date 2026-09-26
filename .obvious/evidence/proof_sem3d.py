"""Semi-3D presentation look (ship-and-rock shading), headless.

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the
real draw paths (Asteroid.draw, Mine.draw, Player.draw over the baked
surfaces):

- proof_sem3d_rock_before.png   the legacy look replicated inline: flat
                                tier-fill circle + chromatic_circle stack
- proof_sem3d_rock_after.png    the same rock through the real draw path —
                                shaded bake under the silhouette ink stack
- proof_sem3d_rocks_strip.png   four seeded rocks tumbled 0/25/50/75°, and
                                their craters/cracks riding the rotation
- proof_sem3d_ship_before.png   the legacy hollow triangle, replicated
- proof_sem3d_ship_after.png    the layered hull at idle throttle
- proof_sem3d_ship_thrust.png   full-throttle plume + both bank extremes
- proof_sem3d_ship_hero.png     the hull at 4× (plume px constants scaled)
- proof_sem3d_budget.png        a worst-case composite frame (background
                                layers, rocks, ship, bursts, halftone)

Self-checks: the shaded interior is not the flat fill (tier hue AND its
dark shade both present), the silhouette is not a circle for at least one
rock (ink beyond the legacy stack's reach), ink outlines ride both
entities, the ship's 25–32px halo band stays paper at full throttle and
full bank, and the composite budget holds. Each before/after pair renders
the same seed at the same center so the diff is the look, nothing else.

Run: uv run python .obvious/evidence/proof_sem3d.py
"""

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

import comicfx
from asteroid import Asteroid, asteroid_shade_colors
from constants import (
    PALETTE,
    PLAYER_RADIUS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from player import Player

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

PAPER = PALETTE["paper"]
INK = comicfx.INK
COMPOSITE_BUDGET_MS = 12.0  # the V4 blueprint budget, re-asserted here
ROCK_RADIUS = 120           # 2× capture scale for the QA floor
ROCK_CENTER = (SCREEN_WIDTH // 2, 340)
FIXED_SEED = 2026

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))


def font(size):
    f = pygame.font.Font(None, size)
    f.set_bold(True)
    return f


def label(surface, text, center):
    glyph = font(40).render(text, True, PALETTE["hud_ink"])
    surface.blit(glyph, glyph.get_rect(center=center))


def count_key(surface, key, box, step=3):
    """Palette-key pixel count inside a box — the presence probe."""
    key_px = PALETTE[key]
    return sum(
        1
        for x in range(box[0], box[2], step)
        for y in range(box[1], box[3], step)
        if surface.get_at((x, y))[:3] == key_px
    )


def count_ink(surface, box, step=1):
    """Full-resolution ink count — the 4px triangle stroke slips between
    sparser sampling grids (measured: step-3 finds 0 of 47 ink px)."""
    return sum(
        1
        for x in range(box[0], box[2], step)
        for y in range(box[1], box[3], step)
        if surface.get_at((x, y))[:3] == INK
    )


def far_ink(surface, center, beyond, box):
    """Ink pixels farther than `beyond` px from center — where the legacy
    circle stack's ink can never reach (its max is radius + ink + fringe)."""
    cx, cy = center
    return sum(
        1
        for x in range(box[0], box[2], 2)
        for y in range(box[1], box[3], 2)
        if (x - cx) ** 2 + (y - cy) ** 2 > beyond * beyond
        and surface.get_at((x, y))[:3] == INK
    )


def wire_asteroids():
    """Fresh sprite groups with Asteroid.containers wired, mirroring main()."""
    updatable, drawable, asteroids = (pygame.sprite.Group() for _ in range(3))
    Asteroid.containers = (asteroids, updatable, drawable)
    return asteroids


# --- the rock, before and after ------------------------------------------------

tier, shadow, _highlight = asteroid_shade_colors(ROCK_RADIUS)
rock_box = (
    ROCK_CENTER[0] - ROCK_RADIUS - 12,
    ROCK_CENTER[1] - ROCK_RADIUS - 12,
    ROCK_CENTER[0] + ROCK_RADIUS + 12,
    ROCK_CENTER[1] + ROCK_RADIUS + 12,
)

before = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
before.fill(PAPER)
# The legacy draw, replicated inline: flat tier fill inside the chromatic
# circle stack — exactly what Asteroid.draw did before this PR.
pygame.draw.circle(before, tier, ROCK_CENTER, ROCK_RADIUS)
comicfx.chromatic_circle(before, tier, ROCK_CENTER, ROCK_RADIUS, 2)
label(before, "BEFORE — FLAT CIRCLE", (ROCK_CENTER[0], 80))
before_tier = count_key(before, "asteroid_l", rock_box)
before_shadow = count_key(before, "asteroid_shadow_l", rock_box)
before_ink = count_ink(before, rock_box)
before_far_ink = far_ink(before, ROCK_CENTER, ROCK_RADIUS + 5, rock_box)
pygame.image.save(before, f"{OUT}/proof_sem3d_rock_before.png")

after = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
after.fill(PAPER)
wire_asteroids()
rock = Asteroid(ROCK_CENTER[0], ROCK_CENTER[1], ROCK_RADIUS, shape_seed=FIXED_SEED)
rock.spin_angle = 0.0
rock.draw(after)                       # the real path: bake + silhouette stack
label(after, "AFTER — SHADED, LUMPY", (ROCK_CENTER[0], 80))
after_tier = count_key(after, "asteroid_l", rock_box)
after_shadow = count_key(after, "asteroid_shadow_l", rock_box)
after_ink = count_ink(after, rock_box)
after_far_ink = far_ink(after, ROCK_CENTER, ROCK_RADIUS + 5, rock_box)
pygame.image.save(after, f"{OUT}/proof_sem3d_rock_after.png")

assert before_tier > 0 and before_ink > 0, "the before frame must show the legacy look"
assert before_shadow == 0, "the before frame is a flat fill — no dark band"
assert after_tier > 0, "the shaded rock keeps its tier hue"
assert after_shadow > 0, "the shaded rock gains the dark band (not a flat fill)"
assert after_ink > 0, "the ink outline rides the new stack"
assert before_far_ink == 0, "the legacy stack's ink stays within radius + fringe"
assert after_far_ink > 0, "at least one rock's silhouette inks beyond r+5 — not a circle"

# --- the tumble strip ----------------------------------------------------------

CELL = 320
strip = pygame.Surface((4 * CELL, 760))
strip.fill(PAPER)
wire_asteroids()
for i, angle in enumerate((0, 25, 50, 75)):
    center = (i * CELL + CELL // 2, 320)
    spinner = Asteroid(center[0], center[1], 110, shape_seed=FIXED_SEED + i)
    spinner.spin_angle = float(angle)
    spinner.draw(strip)
    label(strip, f"SPIN {angle}°  seed {FIXED_SEED + i}", (center[0], 640))
pygame.image.save(strip, f"{OUT}/proof_sem3d_rocks_strip.png")

# --- the ship, before / after / thrust -----------------------------------------

ship_center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)

ship_before = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
ship_before.fill(PAPER)
probe = Player(ship_center[0], ship_center[1])
# The legacy draw, replicated inline: the hollow stroked triangle.
comicfx.chromatic_polygon(ship_before, PALETTE["ship"], probe.triangle(), 2)
label(ship_before, "BEFORE — HOLLOW TRIANGLE", (ship_center[0], 90))
ship_before_box = (ship_center[0] - 40, ship_center[1] - 40, ship_center[0] + 40, ship_center[1] + 40)
before_hull_shade = count_key(ship_before, "ship_hull_shade", ship_before_box)
before_ship_ink = count_ink(ship_before, ship_before_box)
pygame.image.save(ship_before, f"{OUT}/proof_sem3d_ship_before.png")

ship_after = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
ship_after.fill(PAPER)
probe.thrust_level = 0.0
probe.bank_level = 0.0
probe.draw(ship_after)
label(ship_after, "AFTER — LAYERED HULL (IDLE)", (ship_center[0], 90))
after_hull_shade = count_key(ship_after, "ship_hull_shade", ship_before_box)
after_canopy = count_key(ship_after, "ship_canopy", ship_before_box)
after_glow_idle = count_key(ship_after, "engine_glow", ship_before_box)
after_shadow_px = count_key(ship_after, "ship_drop_shadow", ship_before_box)
after_ship_ink = count_ink(ship_after, ship_before_box)
pygame.image.save(ship_after, f"{OUT}/proof_sem3d_ship_after.png")

assert before_hull_shade == 0 and before_ship_ink > 0, "the before ship is hollow ink"
assert after_hull_shade > 0, "the gradient hull fills in"
assert after_canopy > 0, "the canopy and its glint show"
assert after_glow_idle > 0, "the idle ember shows"
assert after_shadow_px > 0, "the drop shadow shows"
assert after_ship_ink > 0, "the ink outline rides the new hull"

thrust = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
thrust.fill(PAPER)
probe.thrust_level = 1.0
probe.bank_level = 1.0
probe.draw(thrust)
label(thrust, "FULL THROTTLE — BANK RIGHT", (ship_center[0], 90))
thrust_glow = count_key(thrust, "engine_glow", ship_before_box)
# The locked halo band, at the presentation maximum: 25–32px, both sides.
band_violations = 0
for side in (1, -1):
    for offset in range(25, 33):
        point = (ship_center[0] + side * offset, ship_center[1])
        if thrust.get_at(point)[:3] != PAPER:
            band_violations += 1
pygame.image.save(thrust, f"{OUT}/proof_sem3d_ship_thrust.png")

assert thrust_glow > after_glow_idle, "the plume brightens with throttle"
assert band_violations == 0, f"the halo band must stay paper ({band_violations} px)"

# --- the ship hero panel (4× detail) --------------------------------------------
# The hull is ~40px at gameplay scale; this panel renders it at 4× so the
# gradient bands, canopy, and plume read for review. The hull geometry and
# canopy scale with radius, but the plume's px constants and the shadow
# offset are absolute (the 25px reach cap serves the native halo budget
# proven above), so they scale with the panel and are restored after.
import player as player_module

HERO_SCALE = 4.0
scaled_names = (
    "ENGINE_GLOW_REACH_IDLE_PX", "ENGINE_GLOW_REACH_THRUST_PX",
    "ENGINE_GLOW_TAIL_INSET", "ENGINE_GLOW_HALF_WIDTH",
    "ENGINE_GLOW_WIDTH_GAIN",
)
originals = {name: getattr(player_module, name) for name in scaled_names}
originals["SHIP_SHADOW_OFFSET"] = player_module.SHIP_SHADOW_OFFSET
for name, value in originals.items():
    if name == "SHIP_SHADOW_OFFSET":
        setattr(player_module, name, (value[0] * HERO_SCALE, value[1] * HERO_SCALE))
    else:
        setattr(player_module, name, value * HERO_SCALE)
hero = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
hero.fill(PAPER)
hero_probe = Player(0, 0)
hero_probe.radius = PLAYER_RADIUS * HERO_SCALE
cells = (
    ((320, 250), 0.0, 0.0, "IDLE — EMBER"),
    ((960, 250), 1.0, 0.0, "FULL THROTTLE"),
    ((320, 590), 1.0, 1.0, "BANK RIGHT"),
    ((960, 590), 1.0, -1.0, "BANK LEFT"),
)
for (cell_x, cell_y), throttle, bank, text in cells:
    hero_probe.position = pygame.Vector2(cell_x, cell_y)
    hero_probe.thrust_level = throttle
    hero_probe.bank_level = bank
    hero_probe.draw(hero)
    label(hero, text, (cell_x, cell_y - 150))
for name, value in originals.items():
    setattr(player_module, name, value)
label(hero, "SHIP DETAIL AT 4× — PLUME PX CONSTANTS SCALED", (SCREEN_WIDTH // 2, 40))
pygame.image.save(hero, f"{OUT}/proof_sem3d_ship_hero.png")

# --- the composite budget -------------------------------------------------------

lines, halftone = comicfx.build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
wire_asteroids()
rocks = []
for i, (x, y) in enumerate(((300, 200), (900, 180), (480, 520), (1020, 540))):
    big_rock = Asteroid(x, y, 90 + 20 * (i % 2), shape_seed=FIXED_SEED + i)
    big_rock.spin_angle = 12.0 * i
    rocks.append(big_rock)
probe.thrust_level = 1.0
frames = 60
start = time.perf_counter()
for _ in range(frames):
    world.fill(PAPER)
    world.blit(lines, (0, 0))
    for big_rock in rocks:
        big_rock.draw(world)
    probe.draw(world)
    screen.blit(world, (0, 0))
    screen.blit(halftone, (0, 0))
elapsed_ms = (time.perf_counter() - start) * 1000 / frames

world.fill(PAPER)
world.blit(lines, (0, 0))
for big_rock in rocks:
    big_rock.draw(world)
probe.draw(world)
screen.blit(world, (0, 0))
screen.blit(halftone, (0, 0))
label(screen, "COMPOSITE BUDGET FRAME", (SCREEN_WIDTH // 2, 40))
pygame.image.save(screen, f"{OUT}/proof_sem3d_budget.png")

assert elapsed_ms <= COMPOSITE_BUDGET_MS, (
    f"composite draw+blit took {elapsed_ms:.2f}ms, budget {COMPOSITE_BUDGET_MS}ms"
)

print("semi-3D evidence OK:")
print(f"  rock before/after  tier px {before_tier} → {after_tier}, shadow px {before_shadow} → {after_shadow}")
print(f"  ink: before {before_ink} px, after {after_ink} px; ink beyond r+5: before {before_far_ink}, after {after_far_ink}")
print(f"  ship: hull-shade px {before_hull_shade} → {after_hull_shade}, canopy {after_canopy}, idle ember {after_glow_idle} → thrust {thrust_glow}")
print(f"  halo band at full throttle+bank: {band_violations} violations")
print(f"  composite draw+blit took {elapsed_ms:.2f}ms/frame, budget {COMPOSITE_BUDGET_MS}ms")
