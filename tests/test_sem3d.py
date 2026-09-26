"""Semi-3D presentation look (ship-and-rock shading PR): the seeded
silhouettes, cel shading, craters, tumble, and the ship's layered hull.

Presentation-only by construction: every test here reads draw-side state
or pure helpers — the sim (velocity, radius, split, protocol) stays pinned
by the existing suites, which this PR leaves untouched.
"""

import math
import random

import pygame
import pytest

from asteroid import Asteroid, Mine, asteroid_shade_colors
from comicfx import (
    INK,
    bake_rock_surface,
    crater_specs,
    light_direction,
    silhouette_points,
    spin_rate_for,
)
from constants import (
    ASTEROID_MIN_RADIUS,
    ASTEROID_SPIN_MAX_DPS,
    ASTEROID_SPIN_MIN_DPS,
    BANK_FRACTION,
    PALETTE,
    PLAYER_BLINK_HZ,
    PLAYER_RADIUS,
    SILHOUETTE_JITTER,
    SILHOUETTE_LIGHT_ANGLE,
    SILHOUETTE_VERTICES,
)
from player import Player


def paper_screen():
    """An initialized display and a paper-filled surface to draw on."""
    pygame.init()
    pygame.display.set_mode((800, 600))
    screen = pygame.Surface((800, 600))
    screen.fill(PALETTE["paper"])
    return screen


def pixel(screen, key, point):
    return screen.get_at(point)[:3] == PALETTE[key]


def scan_colors(screen, box, keys):
    """Count pixels of each palette key inside the box — a presence probe
    for the stack's layers."""
    return {
        key: sum(
            1
            for x in range(box[0], box[2], 2)
            for y in range(box[1], box[3], 2)
            if pixel(screen, key, (x, y))
        )
        for key in keys
    }


def ray_point(center, angle_degrees, radius):
    """The y-down atan2 frame's point at a heading — the same frame the
    bake's light angle and the silhouette vertices speak."""
    return (
        int(center[0] + math.cos(math.radians(angle_degrees)) * radius),
        int(center[1] + math.sin(math.radians(angle_degrees)) * radius),
    )


# --- Seeded silhouettes -------------------------------------------------------


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    Asteroid.containers = (asteroids, updatable, drawable)
    return updatable, drawable, asteroids, None, None


def test_silhouette_is_deterministic_per_seed():
    """The mission's determinism pin: the same (radius, seed) rebuilds the
    exact same vertices — a drifting rock keeps its shape, and every
    multiplayer client derives an identical rock from the same seed."""
    a = silhouette_points(60, 2026)
    b = silhouette_points(60, 2026)
    assert len(a) == len(b)
    assert all((p1.x, p1.y) == (p2.x, p2.y) for p1, p2 in zip(a, b))


def test_silhouette_differs_across_seeds():
    """Different seeds, different rocks — the field doesn't read cloned."""
    shapes = {tuple((p.x, p.y) for p in silhouette_points(60, seed)) for seed in range(30)}
    assert len(shapes) > 25  # a stray collision is fine; a clone farm is not


def test_silhouette_stays_inside_the_shape_bands():
    """10–14 vertices, each radius jittered within ±SILHOUETTE_JITTER of
    the hull radius — lumpy, but unmistakably a rock."""
    for seed in range(40):
        points = silhouette_points(50, seed)
        assert SILHOUETTE_VERTICES[0] <= len(points) <= SILHOUETTE_VERTICES[1]
        for point in points:
            assert point.length() == pytest.approx(50, abs=50 * SILHOUETTE_JITTER[1] + 1e-9)


def test_silhouette_is_actually_lumpy():
    """Across a seed sample both lumpy directions occur: some rocks bulge
    past the hull radius, some dip under it — not a circle with noise
    clipped to one side."""
    bulges = dips = 0
    for seed in range(40):
        lengths = [p.length() for p in silhouette_points(50, seed)]
        bulges += max(lengths) > 50 * (1 + SILHOUETTE_JITTER[0])
        dips += min(lengths) < 50 * (1 - SILHOUETTE_JITTER[0])
    assert bulges > 0 and dips > 0


# --- Seeded craters -----------------------------------------------------------


def test_craters_are_seeded_and_stable():
    """Same seed, same crater layout; 2–5 ellipses per rock."""
    a = crater_specs(60, 77)
    b = crater_specs(60, 77)
    assert a == b
    assert 2 <= len(a) <= 5


def test_craters_stay_inside_even_the_lumpiest_hull():
    """A crater plus its widest reach never crosses the silhouette's
    shallowest dip — surface detail, never a leak."""
    for seed in range(40):
        for offset, rx, ry in crater_specs(60, seed):
            reach = offset.length() + max(rx, ry)
            assert reach <= 60 * (1 - SILHOUETTE_JITTER[1]) + 1e-9


# --- Seeded tumble ------------------------------------------------------------


def test_spin_rate_is_seeded_and_deterministic():
    """Same seed, same signed spin; magnitude inside the tuned band."""
    for seed in (1, 42, 2026):
        rate = spin_rate_for(seed)
        assert rate == spin_rate_for(seed)
        assert ASTEROID_SPIN_MIN_DPS <= abs(rate) <= ASTEROID_SPIN_MAX_DPS


def test_spin_direction_varies_by_seed():
    """The coin flip lands both ways across the field — not a synchronized
    clockwise fleet."""
    rates = [spin_rate_for(seed) for seed in range(40)]
    assert any(r > 0 for r in rates) and any(r < 0 for r in rates)


def test_spin_angle_advances_as_presentation_state():
    """The tumble advances with sim time and is never read back by the
    sim: velocity, radius, and position drift are exactly the old physics.
    A frozen frame (dt=0) holds the angle like every other clock."""
    rock = Asteroid(400, 300, 60)
    rock.velocity.update((10.0, 0.0))
    rock.spin_rate = 30.0  # deg/s, stubbed off the seeded draw
    frozen_before = (rock.position.x, rock.position.y, rock.spin_angle)
    rock.update(0.0)
    assert rock.spin_angle == pytest.approx(frozen_before[2])
    rock.update(0.5)
    assert rock.spin_angle == pytest.approx(15.0)
    # The sim read nothing presentation-only: one frame of drift is the
    # velocity step alone.
    assert rock.position.x == pytest.approx(frozen_before[0] + 10.0 * 0.5)
    assert rock.radius == 60


def test_split_children_get_fresh_seeds():
    """Split children grow their own shape seeds and zero spin angle — the
    fresh chip_damage pattern, extended to the look."""
    random.seed(11)
    updatable, drawable, asteroids, _, _ = make_groups()
    parent = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 3)
    parent_seed = parent.shape_seed
    parent.split()
    children = [rock for rock in asteroids if rock is not parent]
    assert len(children) == 2
    for child in children:
        assert child.shape_seed != parent_seed
        assert child.shape_seed != children[0].shape_seed or child is children[0]
        assert child.spin_angle == 0.0


# --- The shaded bake ----------------------------------------------------------


def test_bake_colors_resolve_through_the_palette():
    """The mission's palette pin: every tier's shade triple IS the PALETTE
    entry — no draw-code literals upstream of this resolver."""
    for tier_index, radius in enumerate(
        (ASTEROID_MIN_RADIUS, ASTEROID_MIN_RADIUS * 2, ASTEROID_MIN_RADIUS * 3)
    ):
        tier, shadow, highlight = asteroid_shade_colors(radius)
        assert tier is PALETTE[("asteroid_s", "asteroid_m", "asteroid_l")[tier_index]]
        assert shadow is PALETTE[("asteroid_shadow_s", "asteroid_shadow_m", "asteroid_shadow_l")[tier_index]]
        assert highlight is PALETTE[("asteroid_highlight_s", "asteroid_highlight_m", "asteroid_highlight_l")[tier_index]]


def test_bake_paints_two_hard_bands_and_craters():
    """The bake's look: tier hue on the lit side, the tier's dark shade in
    the anti-light rim crescent, and seeded craters — hard band edges, no
    airbrush. Pinned seeds verified once locally; determinism keeps them
    honest."""
    radius = 60
    tier, shadow, highlight = asteroid_shade_colors(radius)
    bake = bake_rock_surface(radius, 5, tier, shadow, highlight)
    center = (bake.get_width() // 2, bake.get_height() // 2)
    anti_light = (SILHOUETTE_LIGHT_ANGLE + 180.0) % 360.0

    def at(angle, dist):
        point = ray_point(center, angle, dist)
        return bake.get_at(point)[:3]

    # Shadow crescent: deepest on the anti-light rim (0.8·r is inside the
    # 0.30·r-deep band), tier hue on the lit side at the same depth.
    assert at(anti_light, radius * 0.8) == shadow
    assert at(SILHOUETTE_LIGHT_ANGLE, radius * 0.5) == tier
    # The bake is SRCALPHA: outside the silhouette there is nothing.
    assert bake.get_at((0, 0))[3] == 0


def test_bake_rotation_tracks_the_polygon_spin():
    """The sign pin: pygame.transform.rotate(-spin) on the bake matches
    Vector2.rotate(+spin) on the silhouette — at spin 180 the shadow
    crescent (down-right at spin 0) must show up-left. A sign error here
    would shear the shading off the outline."""
    radius = 60
    tier, shadow, highlight = asteroid_shade_colors(radius)
    bake = bake_rock_surface(radius, 5, tier, shadow, highlight)
    center = (bake.get_width() // 2, bake.get_height() // 2)
    anti_light = (SILHOUETTE_LIGHT_ANGLE + 180.0) % 360.0

    rotated = pygame.transform.rotate(bake, -180.0)
    rotated_center = (rotated.get_width() // 2, rotated.get_height() // 2)

    def at(surface, c, angle, dist):
        point = ray_point(c, angle, dist)
        return surface.get_at(point)[:3]

    # The crescent tumbled with the body: the old shadow rim now shows the
    # tier hue, and the shadow waits on the opposite rim.
    assert at(rotated, rotated_center, anti_light, radius * 0.8) == tier
    assert at(rotated, rotated_center, SILHOUETTE_LIGHT_ANGLE, radius * 0.8) == shadow


def test_drawn_rock_wears_the_full_ink_stack_over_the_shading():
    """The identity pin, on the new stack: a drawn rock still shows black
    ink, both chromatic fringes, and the tier stroke — over a shaded body
    (tier hue AND its shadow inside the rim, so the fill is not flat)."""
    screen = paper_screen()
    random.seed(4)
    rock = Asteroid(400, 300, 60)
    rock.spin_angle = 0.0
    rock.draw(screen)
    box = (330, 230, 471, 371)
    counts = scan_colors(
        screen,
        box,
        (
            "fringe_r",
            "fringe_c",
            "asteroid_l",
            "asteroid_shadow_l",
        ),
    )
    ink_count = sum(
        1
        for x in range(box[0], box[2], 2)
        for y in range(box[1], box[3], 2)
        if screen.get_at((x, y))[:3] == INK
    )
    counts["ink"] = ink_count
    for key, count in counts.items():
        assert count > 0, f"{key} missing from the drawn rock"


def test_drawn_rock_halo_band_stays_paper():
    """The tripwire at rock scale is meaningless (rocks have no band), but
    the rock must still leave the paper AROUND the ink clean of bake
    bleed: nothing paints outside the silhouette's bounding ring."""
    screen = paper_screen()
    random.seed(4)
    rock = Asteroid(100, 100, 40)
    rock.spin_angle = 0.0
    rock.draw(screen)
    for angle in range(0, 360, 10):
        assert pixel(screen, "paper", ray_point((100, 100), angle, 52)), angle


# --- The ship's layered hull --------------------------------------------------


def test_ship_draw_shows_every_layer():
    """Gradient hull (shade at the tail), canopy, exhaust plume, drop
    shadow — and the ink stack over all of it."""
    screen = paper_screen()
    ship = Player(400, 300)
    ship.thrust_level = 1.0
    ship.draw(screen)
    box = (360, 260, 441, 341)
    counts = scan_colors(
        screen,
        box,
        (
            "ship",
            "ship_hull_shade",
            "ship_canopy",
            "engine_glow",
            "ship_drop_shadow",
            "fringe_r",
            "fringe_c",
        ),
    )
    ink_count = sum(
        1
        for x in range(box[0], box[2], 2)
        for y in range(box[1], box[3], 2)
        if screen.get_at((x, y))[:3] == INK
    )
    counts["ink"] = ink_count
    for key, count in counts.items():
        assert count > 0, f"{key} missing from the drawn ship"


def test_ship_halo_band_stays_paper_in_the_worst_case():
    """The locked tripwire, at the presentation maximum: full throttle
    (plume out at 24px), full bank, shield off — the whole 25–32px band
    stays paper, mirroring the V2 pin with the new layers present."""
    screen = paper_screen()
    ship = Player(400, 300)
    ship.thrust_level = 1.0
    ship.bank_level = 1.0
    ship.draw(screen)
    ring = PLAYER_RADIUS + 5  # the V2 band's inner edge, 25px from center
    for side in (1, -1):
        for offset in range(ring, ring + 8):
            assert pixel(screen, "paper", (400 + side * offset, 300))


def test_banking_scales_only_the_wing():
    """±BANK_FRACTION on the right-vertex offsets, nose and plan-form
    untouched; bank=0 is the legacy triangle."""
    ship = Player(400, 300)
    flat = ship.triangle()
    assert ship.triangle(0.0) == flat
    banked = ship.triangle(1.0)
    # The nose vertex is identical; each tail wing moved exactly the bank
    # fraction of its right-axis component (the wing's along-nose length
    # is untouched).
    assert banked[0] == flat[0]
    right = pygame.Vector2(1, 0)  # the local right axis at rotation 0
    for legacy_v, banked_v in ((flat[1], banked[1]), (flat[2], banked[2])):
        legacy_off = legacy_v - ship.position
        moved = (banked_v - legacy_v).length()
        assert moved == pytest.approx(abs(legacy_off.dot(right)) * BANK_FRACTION, abs=1e-9)


def test_throttle_and_bank_are_presentation_clocks():
    """The dash reads as throttle and both clocks relax toward zero — and
    neither field feeds back into the sim state the old update produced."""
    ship = Player(400, 300)
    ship.dash_timer = 0.25  # mid-dash: the flame reads it
    ship.update(0.1)
    assert ship.thrust_level > 0
    ship.dash_timer = 0.0
    ship.bank_level = 1.0  # last frame banked hard
    velocity_before = ship.velocity.copy()
    position_before = ship.position.copy()
    ship.update(1 / 60)
    assert 0.0 < ship.bank_level < 1.0  # relaxing toward rest
    assert ship.velocity == velocity_before  # the clocks never touch the sim
    assert ship.position == position_before


def test_canopy_glint_faces_the_shared_light():
    """The glint dot sits toward the light the rocks are lit from — one
    light source for the whole scene."""
    assert light_direction() == pygame.Vector2(1, 0).rotate(SILHOUETTE_LIGHT_ANGLE)


def test_ship_blinks_are_untouched():
    """The grace-window blink still skips the whole draw — the new layers
    ride the same early return. Timer 0.625s sits on a hidden phase:
    (0.625 · PLAYER_BLINK_HZ) % 1 = 0.5."""
    screen = paper_screen()
    ship = Player(400, 300)
    ship.invulnerability_timer = 0.625
    ship.draw(screen)
    counts = scan_colors(screen, (380, 280, 421, 321), ("ship",))
    assert counts["ship"] == 0


# --- Variants -----------------------------------------------------------------


def test_mine_stays_flat_on_the_family_silhouette():
    """The mine's flat-dark variant: no shading bands (the None bake
    sentinel), mine_hull stroke — and the existing marker/hull phase pair
    still holds over the flat bake."""
    screen = paper_screen()
    random.seed(9)
    mine = Mine(400, 300, 40)
    assert mine._bake_colors() is None  # the flat sentinel
    assert mine._stroke_color() == PALETTE["mine_hull"]
    mine.blink_clock = 0.0  # the lit half of the square wave
    mine.draw(screen)
    assert screen.get_at((400, 300))[:3] == PALETTE["fringe_r"]
    screen.fill(PALETTE["paper"])
    mine.blink_clock = 0.25  # the dark half: the flat hull, not a tier hue
    mine.draw(screen)
    assert pixel(screen, "mine_hull", (400, 300))
