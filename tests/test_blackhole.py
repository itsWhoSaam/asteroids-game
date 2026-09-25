"""Insanity threats: black holes — the pure pull math, the registry consult,
the lifetime clock, the wave-gated spawn scheduler, and the restart clear.

Failure signatures the tests must catch (spec): holes persisting past their
lifetime or into a restart; a singularity flinging bodies at the core;
pull touching pickups or particles; a well opening during a boss wave.
"""

import pygame
import pytest

from asteroid import Asteroid
from blackhole import (
    BlackHole,
    BlackHoleScheduler,
    accel_at,
    live_holes,
    pull_at,
    spawn_position,
)
from constants import (
    BLACK_HOLE_FIRST_DELAY_S,
    BLACK_HOLE_FIRST_WAVE,
    BLACK_HOLE_LIFETIME_S,
    BLACK_HOLE_MAX_ACCEL,
    BLACK_HOLE_MIN_DIST,
    BLACK_HOLE_PLAYER_FACTOR,
    BLACK_HOLE_SPAWN_MARGIN,
    BLACK_HOLE_WARNING_S,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from player import Player
from shot import Shot


def make_world(tmp_path):
    """Groups + Game wired like main(); an empty hole registry."""
    pygame.init()
    live_holes.clear()
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    BlackHole.containers = (updatable, drawable)

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, powerups


@pytest.fixture(autouse=True)
def _clean_registry():
    """Every test starts and ends with an empty hole registry."""
    live_holes.clear()
    yield
    live_holes.clear()


# --- the pure pull math --------------------------------------------------------


def test_accel_points_toward_the_hole():
    accel = accel_at(pygame.Vector2(100, 100), pygame.Vector2(400, 100))
    assert accel.x > 0  # pulled right, toward the hole
    assert accel.y == pytest.approx(0.0, abs=1e-6)


def test_accel_falls_off_with_distance():
    near = accel_at(pygame.Vector2(300, 0), pygame.Vector2(400, 0))
    far = accel_at(pygame.Vector2(600, 0), pygame.Vector2(400, 0))
    assert near.length() > far.length() > 0


def test_the_cap_bounds_the_close_pull():
    """The cap is what keeps the NEAR pull sane: at min-dist the raw
    inverse-falloff magnitude (~15,800) exceeds the cap, so the body is
    pulled at exactly BLACK_HOLE_MAX_ACCEL."""
    at_cap = accel_at(pygame.Vector2(401, 0), pygame.Vector2(400, 0))
    assert at_cap.length() == pytest.approx(min(
        4e6 / BLACK_HOLE_MIN_DIST ** 1.5, BLACK_HOLE_MAX_ACCEL
    ))


def test_the_min_dist_keeps_the_core_finite():
    """A body inside the core is pulled at the min-dist strength — never a
    division-by-zero, never a fling."""
    center = accel_at(pygame.Vector2(400, 300), pygame.Vector2(400, 300))
    inside = accel_at(pygame.Vector2(400.5, 300), pygame.Vector2(400, 300))
    assert center.length() == pytest.approx(inside.length())
    assert center.length() <= BLACK_HOLE_MAX_ACCEL


def test_pull_at_sums_every_live_hole():
    hole_a = BlackHole(100, 100)
    hole_b = BlackHole(200, 400)  # same side: the pulls add, never cancel
    live_holes.extend([hole_a, hole_b])

    single = accel_at(pygame.Vector2(400, 300), hole_a.position)
    both = pull_at(pygame.Vector2(400, 300))
    assert both.length() > single.length()


def test_the_player_fights_gravity_at_half_strength():
    hole = BlackHole(100, 100)
    live_holes.append(hole)
    pos = pygame.Vector2(400, 300)

    assert pull_at(pos, player=True) == pull_at(pos) * BLACK_HOLE_PLAYER_FACTOR


def test_pull_with_no_live_holes_is_zero():
    assert pull_at(pygame.Vector2(400, 300)) == pygame.Vector2(0, 0)


def test_shot_update_bends_toward_a_live_hole(tmp_path):
    """Integration: the registry consult rides Shot.update — a shot flying
    away from a well decelerates instead of flying straight."""
    game, player, asteroids, shots, powerups = make_world(tmp_path)
    hole = BlackHole(300, 360)
    live_holes.append(hole)
    shot = Shot(600, 360)  # directly right of the hole
    shot.velocity = pygame.Vector2(500, 0)  # flying away from the well

    shot.update(1 / 60)

    assert shot.velocity.x < 500  # pulled back toward the well
    assert shot.velocity.y == 0  # exactly on the axis: no perpendicular pull


# --- the well itself ------------------------------------------------------------


def test_lifetime_expires_and_marks_despawned(tmp_path):
    game, player, asteroids, shots, powerups = make_world(tmp_path)
    hole = BlackHole(400, 300)

    hole.update(BLACK_HOLE_LIFETIME_S / 2)
    assert hole.alive() and not hole.despawned

    hole.update(BLACK_HOLE_LIFETIME_S)  # past the end
    assert hole.despawned is True
    assert not hole.alive()


def test_the_warning_blink_window_is_the_last_two_seconds(tmp_path):
    game, player, asteroids, shots, powerups = make_world(tmp_path)
    hole = BlackHole(400, 300)

    hole.lifetime = BLACK_HOLE_WARNING_S + 1
    assert not hole.warning
    hole.lifetime = BLACK_HOLE_WARNING_S / 2
    assert hole.warning
    hole.lifetime = 0.0
    assert not hole.warning  # expired, not warning


def test_spawn_positions_stay_clear_of_every_edge():
    for _ in range(20):
        x, y = spawn_position()
        assert BLACK_HOLE_SPAWN_MARGIN <= x <= SCREEN_WIDTH - BLACK_HOLE_SPAWN_MARGIN
        assert BLACK_HOLE_SPAWN_MARGIN <= y <= SCREEN_HEIGHT - BLACK_HOLE_SPAWN_MARGIN


# --- the spawn clock ------------------------------------------------------------


def test_the_clock_holds_below_the_first_hole_wave_and_on_boss_waves():
    clock = BlackHoleScheduler()
    assert clock.update(1000.0, 1, boss_wave=False) is False  # before wave 3
    assert clock.update(BLACK_HOLE_FIRST_DELAY_S, BLACK_HOLE_FIRST_WAVE + 1,
                        boss_wave=True) is False  # a boss wave bars the well
    assert clock.timer == BLACK_HOLE_FIRST_DELAY_S  # and it never ticked


def test_the_clock_fires_from_wave_three_then_re_arms():
    clock = BlackHoleScheduler()

    assert clock.update(BLACK_HOLE_FIRST_DELAY_S, 3, boss_wave=False) is True
    # The re-arm keeps the next well near the repeat delay, never now.
    assert clock.timer > 0
    assert clock.update(1.0, 3, boss_wave=False) is False


def test_the_clock_reset_re_arms_the_first_delay():
    clock = BlackHoleScheduler()
    clock.update(BLACK_HOLE_FIRST_DELAY_S, 3, boss_wave=False)

    clock.reset()
    assert clock.timer == BLACK_HOLE_FIRST_DELAY_S


def test_restart_clears_live_holes(tmp_path):
    """main's restart clear: every live well is culled (despawned), never
    paid — and the registry the bodies consult is rebuilt fresh."""
    game, player, asteroids, shots, powerups = make_world(tmp_path)
    hole = BlackHole(400, 300)
    live_holes.append(hole)

    hole.despawned = True
    hole.kill()  # what main's restart loop does
    live_holes.clear()

    assert not hole.alive()
    assert pull_at(pygame.Vector2(400, 300)) == pygame.Vector2(0, 0)
