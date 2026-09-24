"""Tests for the idle click surface: chip damage on Asteroid, the
destruction-diff mint detector from main.py, cursor picking, and the
floating '+N' credit numbers."""

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    CLICK_DAMAGE_BASE,
    FLOAT_LIFETIME_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from hud import points_for
from main import FloatingText, asteroid_at, destroyed_asteroids, float_label
from shot import Shot


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)

    return updatable, drawable, asteroids, shots


# --- chip damage ----------------------------------------------------------


def test_clicks_chip_below_threshold_without_killing():
    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 3)  # large: 3 tiers
    assert big.chip_threshold == pytest.approx(9.0)
    for _ in range(8):
        assert big.take_chip(CLICK_DAMAGE_BASE) is False
        assert big.alive()
    assert big.chip_damage == pytest.approx(8.0)


def test_chip_thresholds_scale_with_size_tier():
    small = Asteroid(0, 0, ASTEROID_MIN_RADIUS)
    medium = Asteroid(0, 0, ASTEROID_MIN_RADIUS * 2)
    large = Asteroid(0, 0, ASTEROID_MIN_RADIUS * 3)
    assert small.chip_threshold < medium.chip_threshold < large.chip_threshold
    assert medium.chip_threshold == pytest.approx(2 * small.chip_threshold)
    assert large.chip_threshold == pytest.approx(3 * small.chip_threshold)


def test_crossing_threshold_dies_through_the_split_path():
    _updatable, _drawable, asteroids, _shots = make_groups()
    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 3)
    assert big.take_chip(big.chip_threshold) is True
    assert not big.alive()
    assert len(asteroids) == 2  # split() children spawned into the group
    for child in list(asteroids):
        assert child.chip_damage == 0.0  # fresh chips, no carryover
        assert child.radius == ASTEROID_MIN_RADIUS * 2


def test_dead_asteroid_ignores_further_chips():
    _updatable, _drawable, asteroids, _shots = make_groups()
    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS)
    big.take_chip(big.chip_threshold)
    assert big.take_chip(CLICK_DAMAGE_BASE) is False
    assert len(asteroids) == 0  # and no second split happened


def test_split_stays_instant_kill_regardless_of_chips():
    """Shots call split() directly — the chip threshold never gates them."""
    _updatable, _drawable, asteroids, _shots = make_groups()
    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 3)
    big.chip_damage = big.chip_threshold - 1.0  # almost chipped through
    big.split()  # what a shot hit calls — one hit, no threshold
    assert not big.alive()
    assert len(asteroids) == 2


# --- destruction diff -----------------------------------------------------


def test_chip_to_kill_mints_exactly_once_with_no_double_pay(tmp_path):
    """The full idle pipeline: clicks whittle, the diff detects the death,
    the ledger pays for the parent once — split children never pay."""
    _updatable, _drawable, asteroids, _shots = make_groups()
    economy = Economy(save_path=str(tmp_path / "game_save.json"))

    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 3)  # large → 20 points
    prev = set(asteroids)

    while big.alive():
        big.take_chip(CLICK_DAMAGE_BASE)

    destroyed = destroyed_asteroids(prev, asteroids)
    assert len(destroyed) == 1
    assert destroyed[0] is big

    for wreck in destroyed:
        economy.mint(wreck.radius)
    assert economy.credits == points_for(ASTEROID_MIN_RADIUS * 3) == 20

    # The next frame: children are on screen, nothing new has died.
    assert len(asteroids) == 2
    assert destroyed_asteroids(set(asteroids), asteroids) == []
    assert economy.credits == 20.0


def test_shot_kills_mint_through_the_same_diff(tmp_path):
    """Shots keep their instant-kill split(); the diff mints for them too."""
    _updatable, _drawable, asteroids, _shots = make_groups()
    economy = Economy(save_path=str(tmp_path / "game_save.json"))

    big = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 2)
    prev = set(asteroids)
    big.split()  # what handle_collisions does on a shot hit

    destroyed = destroyed_asteroids(prev, asteroids)
    assert len(destroyed) == 1 and destroyed[0] is big
    for wreck in destroyed:
        economy.mint(wreck.radius)
    assert economy.credits == points_for(ASTEROID_MIN_RADIUS * 2) == 50


def test_culled_asteroid_never_mints():
    """A rock that drifted off-screen was culled, not destroyed."""
    _updatable, _drawable, asteroids, _shots = make_groups()
    drifter = Asteroid(SCREEN_WIDTH + 200, SCREEN_HEIGHT + 200, 40)
    prev = set(asteroids)

    drifter.update(0.016)  # off-screen → despawned + kill

    assert drifter.despawned
    assert destroyed_asteroids(prev, asteroids) == []


# --- cursor picking -------------------------------------------------------


def test_asteroid_at_picks_the_rock_under_the_cursor():
    _updatable, _drawable, asteroids, _shots = make_groups()
    a = Asteroid(400, 300, ASTEROID_MIN_RADIUS)
    b = Asteroid(410, 300, ASTEROID_MIN_RADIUS)

    assert asteroid_at(asteroids, (400, 300)) is a
    assert asteroid_at(asteroids, (410, 300)) is b
    assert asteroid_at(asteroids, (700, 300)) is None  # empty space


def test_asteroid_at_prefers_the_closest_when_rocks_overlap():
    _updatable, _drawable, asteroids, _shots = make_groups()
    a = Asteroid(400, 300, ASTEROID_MIN_RADIUS * 2)
    b = Asteroid(415, 300, ASTEROID_MIN_RADIUS * 2)

    assert asteroid_at(asteroids, (402, 300)) is a  # 2 px from a, 13 from b
    assert asteroid_at(asteroids, (414, 300)) is b  # 14 px from a, 1 from b


# --- floating credit numbers ----------------------------------------------


def test_float_label_renders_whole_numbers():
    assert float_label(20) == "+20"
    assert float_label(30.625) == "+30"


def test_floating_text_rises_and_expires_on_the_dt_timer():
    floaters = pygame.sprite.Group()
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    FloatingText.containers = (floaters, updatable, drawable)
    try:
        floater = FloatingText(400, 300, 20)
        assert floater.lifetime == FLOAT_LIFETIME_SECONDS
        assert floater.surface.get_width() > 0  # "+20" actually rendered

        top = floater.position.y
        floater.update(0.5)
        assert floater.position.y < top  # rising
        assert floater.alive()

        floater.update(FLOAT_LIFETIME_SECONDS)  # total elapsed ≥ lifetime
        assert not floater.alive()
        assert len(floaters) == 0
    finally:
        FloatingText.containers = ()
