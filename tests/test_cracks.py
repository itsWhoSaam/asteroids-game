"""Tests for the chip-damage crack overlay (Tier 2): the pure crack_stage
gate from chip damage and size tier, the seeded ink web in comicfx, and
the split reset that leaves children uncracked.

Draw checks are headless smoke with ink-pixel assertions on a paper-filled
surface — the dummy-driver contract (plain strokes, no per-pixel alpha).
"""

import pygame
import pytest

from asteroid import Asteroid, chip_threshold_for, crack_stage
from comicfx import (
    CRACK_INNER_FRACTION,
    CRACK_LINES_PER_STAGE,
    CRACK_REACH_FRACTION,
    INK,
    crack_polylines,
    draw_cracks,
)
from constants import (
    ASTEROID_MIN_RADIUS,
    CHIP_CRACK_FRACTIONS,
    CHIP_HEALTH_PER_TIER,
    CLICK_DAMAGE_BASE,
)

PAPER = (23, 18, 58)  # PALETTE["paper"], inlined for plain-pixel comparisons

TIERS = (
    ASTEROID_MIN_RADIUS,
    ASTEROID_MIN_RADIUS * 2,
    ASTEROID_MIN_RADIUS * 3,
)

MAX_STAGE = len(CHIP_CRACK_FRACTIONS)


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    return updatable, drawable, asteroids


def stage_damage(stage, radius):
    """Chip damage that reads as `stage`: zero for stage 0, else the
    stage's own mark fraction of the rock's chip threshold."""
    if stage == 0:
        return 0.0
    return CHIP_CRACK_FRACTIONS[stage - 1] * chip_threshold_for(radius)


# --- crack_stage: boundaries -------------------------------------------------


def test_untouched_rocks_have_no_cracks():
    for radius in TIERS:
        assert crack_stage(0.0, radius) == 0


def test_crack_stage_never_reads_negative_damage():
    assert crack_stage(-1.0, ASTEROID_MIN_RADIUS * 3) == 0


@pytest.mark.parametrize("mark_index", range(MAX_STAGE))
def test_stage_crosses_exactly_at_each_mark(mark_index):
    """Crossing is inclusive: at a mark the next stage shows, just below
    it the rock still reads the previous one."""
    radius = ASTEROID_MIN_RADIUS * 3
    threshold = chip_threshold_for(radius)
    at = crack_stage(CHIP_CRACK_FRACTIONS[mark_index] * threshold, radius)
    below = crack_stage(CHIP_CRACK_FRACTIONS[mark_index] * threshold - 0.001, radius)
    assert at == mark_index + 1
    assert below == mark_index


def test_overshoot_damage_clamps_at_the_last_stage():
    radius = ASTEROID_MIN_RADIUS
    assert crack_stage(chip_threshold_for(radius) * 10, radius) == MAX_STAGE


# --- crack_stage: monotonicity + tier scaling --------------------------------


def test_stage_never_decreases_as_damage_grows():
    radius = ASTEROID_MIN_RADIUS * 2
    threshold = chip_threshold_for(radius)
    stages = [crack_stage(threshold * i / 100, radius) for i in range(101)]
    assert all(a <= b for a, b in zip(stages, stages[1:]))
    assert stages[0] == 0 and stages[-1] == MAX_STAGE


def test_same_damage_cracks_a_small_rock_deeper():
    damage = CHIP_HEALTH_PER_TIER  # one tier's worth of clicks
    small = crack_stage(damage, ASTEROID_MIN_RADIUS)
    large = crack_stage(damage, ASTEROID_MIN_RADIUS * 3)
    assert small > large  # 3/3 — the final stage vs 3/9 — the first


def test_stage_tracks_a_real_click_sequence():
    """The gate reads the same threshold the clicks kill by: on a large
    rock, the sixth base click crosses the 0.50 mark, the seventh the
    0.75 mark, and the rock stays alive under the whole sequence."""
    updatable, drawable, asteroids = make_groups()
    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 3)  # threshold 9.0
    stages = []
    for _ in range(8):
        assert big.take_chip(CLICK_DAMAGE_BASE) is False
        stages.append(crack_stage(big.chip_damage, big.radius))
    assert stages == sorted(stages)
    assert stages[5] == 2  # 6/9 crossed the 0.50 mark
    assert stages[6] == 3  # 7/9 crossed the 0.75 mark
    assert big.alive()


# --- split reset -------------------------------------------------------------


def test_split_children_reset_to_the_uncracked_stage():
    updatable, drawable, asteroids = make_groups()
    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 3)
    big.chip_damage = big.chip_threshold * 0.8
    assert crack_stage(big.chip_damage, big.radius) == MAX_STAGE

    big.split()

    assert len(asteroids) == 2
    for child in list(asteroids):
        assert child.chip_damage == 0.0  # fresh chips, no carryover
        assert crack_stage(child.chip_damage, child.radius) == 0


def test_chip_seed_is_a_plain_int_seed():
    """Each rock carries its own integer pattern seed — the value
    random.Random consumes, which is what keeps a drifting rock's web
    fixed while it deepens. Determinism is pinned at the web level below."""
    rock = Asteroid(0, 0, ASTEROID_MIN_RADIUS)
    assert isinstance(rock.crack_seed, int)
    assert 0 <= rock.crack_seed < 2**32


# --- the comicfx web: purity and geometry ------------------------------------


def test_crack_web_is_deterministic_per_seed():
    assert crack_polylines(40, 1234) == crack_polylines(40, 1234)


def test_crack_web_varies_by_seed():
    assert crack_polylines(40, 1) != crack_polylines(40, 2)


def test_crack_web_sizes_to_the_full_stage_count():
    web = crack_polylines(40, 7)
    assert len(web) == CRACK_LINES_PER_STAGE * MAX_STAGE
    assert all(len(polyline) == 3 for polyline in web)  # start, jag, reach


def test_crack_web_stays_inside_the_hull():
    """Every vertex sits between the inner offset and the reach fraction of
    the hull radius — no crack pokes outside the rock it cracks."""
    for polyline in crack_polylines(40, 9):
        for point in polyline:
            assert point.length() <= 40 * CRACK_REACH_FRACTION + 1e-9
            assert point.length() >= 40 * CRACK_INNER_FRACTION - 1e-9


def test_draw_cracks_is_a_noop_at_stage_zero():
    """Stage 0 draws nothing — the untouched hull stays clean."""
    pygame.init()
    surface = pygame.Surface((100, 100))
    surface.fill(PAPER)
    draw_cracks(surface, (50, 50), 30, 0, 42)
    assert surface.get_at((50, 50))[:3] == PAPER


# --- draw smoke at each stage ------------------------------------------------


def draw_stage_frame(stage, radius, seed=11):
    """One asteroid at a given stage, drawn onto a paper-filled surface —
    the real render's world fill, the one ink reads against."""
    pygame.init()
    surface = pygame.Surface((200, 200))
    surface.fill(PAPER)
    rock = Asteroid(100, 100, radius)
    rock.chip_damage = stage_damage(stage, radius)
    rock.crack_seed = seed
    rock.draw(surface)  # smoke: must not raise under the dummy drivers
    return surface


def interior_ink(surface):
    """Ink pixels strictly inside the hull ring — sampled as a disc of
    0.85·radius around the center, so the chromatic ring (which lives at
    radius + stroke and beyond) can never bleed into the count; only
    crack strokes can paint here."""
    cx, cy = 100, 100
    reach = int(40 * 0.85)
    limit = reach * reach
    return sum(
        1
        for x in range(cx - reach, cx + reach + 1)
        for y in range(cy - reach, cy + reach + 1)
        if (x - cx) ** 2 + (y - cy) ** 2 <= limit
        and surface.get_at((x, y))[:3] == INK
    )


@pytest.mark.parametrize("stage", range(MAX_STAGE + 1))
def test_draw_smoke_at_each_stage(stage):
    surface = draw_stage_frame(stage, 40)
    if stage == 0:
        assert interior_ink(surface) == 0
    else:
        assert interior_ink(surface) > 0


def test_cracks_deepen_visibly_with_the_stage():
    """The web must be visible, not just legal: stage 3 paints strictly
    more interior ink than stage 1."""
    stage1 = interior_ink(draw_stage_frame(1, 40))
    stage3 = interior_ink(draw_stage_frame(3, 40))
    assert stage3 > stage1 > 0
