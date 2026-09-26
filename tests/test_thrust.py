"""Physics overhaul: Newtonian thrust — nose acceleration, coasting under
damping, the speed ceiling, ship-only wrap, and the frozen-frame no-op.

Failure signatures the tests must catch (spec): thrust that ignores
rotation, a velocity that zeroes on key release, a cap above the
anti-tunnel ceiling, a ship lost off-screen, gravity applied as a position
drift, and integrators that creep during hit-stop.
"""

import math
from collections import defaultdict

import pygame
import pytest

import blackhole
from constants import (
    PLAYER_LINEAR_DAMPING,
    PLAYER_MAX_SPEED,
    PLAYER_RADIUS,
    PLAYER_RETRO_FACTOR,
    PLAYER_THRUST_ACCEL,
    PLAYER_TURN_SPEED,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from player import Player


def press(monkeypatch, *keys):
    """Poll exactly the given keys (the test_chaos_pickups pattern)."""
    pressed = defaultdict(int)
    for key in keys:
        pressed[key] = 1
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: pressed)
    return pressed


def release_all(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: defaultdict(int))


# --- Thrust along the nose ---------------------------------------------------


def test_thrust_accelerates_along_the_nose(monkeypatch):
    """One W frame builds velocity along the rotated nose: 600 px/s^2 for
    a tenth of a second, damped one frame."""
    pygame.init()
    player = Player(640, 360)
    player.rotation = 90  # the nose now points (-1, 0)
    nose = pygame.Vector2(0, 1).rotate(player.rotation)
    press(monkeypatch, pygame.K_w)

    player.update(0.1)

    expected = nose * PLAYER_THRUST_ACCEL * 0.1
    expected *= math.exp(-PLAYER_LINEAR_DAMPING * 0.1)
    assert player.velocity.distance_to(expected) < 1e-9


def test_rotation_rate_is_unchanged(monkeypatch):
    """A/D still turn at PLAYER_TURN_SPEED deg/s — the overhaul touched
    translation, not steering."""
    pygame.init()
    player = Player(640, 360)
    press(monkeypatch, pygame.K_d)

    player.update(1 / 60)

    assert player.rotation == pytest.approx(PLAYER_TURN_SPEED * (1 / 60))


def test_retro_thrust_opposes_the_nose_at_its_fraction(monkeypatch):
    """S thrusts opposite the nose at PLAYER_RETRO_FACTOR of the main
    engine — a brake that can reverse you, not a second full thruster."""
    pygame.init()
    player = Player(640, 360)
    nose = pygame.Vector2(0, 1).rotate(player.rotation)
    press(monkeypatch, pygame.K_s)

    player.update(1 / 60)

    expected = -nose * PLAYER_THRUST_ACCEL * PLAYER_RETRO_FACTOR * (1 / 60)
    expected *= math.exp(-PLAYER_LINEAR_DAMPING * (1 / 60))
    assert player.velocity.distance_to(expected) < 1e-9


# --- Coast and inertia --------------------------------------------------------


def test_releasing_the_keys_leaves_the_ship_coasting(monkeypatch):
    """Momentum persists: after the keys release the ship keeps gliding
    along its last heading, monotonically slowing — never stopping dead."""
    pygame.init()
    player = Player(640, 360)
    press(monkeypatch, pygame.K_w)
    for _ in range(30):
        player.update(1 / 60)
    release_all(monkeypatch)

    lengths = []
    for _ in range(10):
        player.update(1 / 60)
        lengths.append(player.velocity.length())

    assert all(v > 0 for v in lengths), "the ship stopped dead on release"
    assert all(a > b for a, b in zip(lengths, lengths[1:])), (
        "coast speed is not monotonically decaying"
    )


def test_coast_decays_by_the_damping_law_exactly(monkeypatch):
    """The decay is the shared linear damping — one law for thrust, dash,
    and pull momentum alike."""
    pygame.init()
    player = Player(640, 360)
    press(monkeypatch, pygame.K_w)
    player.update(1 / 60)
    release_all(monkeypatch)
    v0 = player.velocity.length()

    player.update(1 / 60)

    assert player.velocity.length() == pytest.approx(
        v0 * math.exp(-PLAYER_LINEAR_DAMPING * (1 / 60))
    )


def test_thrust_saturates_at_the_speed_ceiling(monkeypatch):
    """Held thrust tops out at PLAYER_MAX_SPEED — the anti-tunnel cap."""
    pygame.init()
    player = Player(640, 360)
    press(monkeypatch, pygame.K_w)

    for _ in range(600):  # ten simulated seconds
        player.update(1 / 60)

    assert player.velocity.length() == pytest.approx(PLAYER_MAX_SPEED)


# --- Black-hole pull ----------------------------------------------------------


def test_black_hole_pull_integrates_into_velocity(monkeypatch):
    """Gravity is an acceleration now, not a position drift: the pull adds
    to velocity (half strength for the ship, pinned in test_blackhole) and
    the position follows the velocity. The old drift moved the ship 8 px
    in this step; the integration moves it velocity * dt instead."""
    pygame.init()
    player = Player(640, 360)
    monkeypatch.setattr(
        blackhole, "pull_at", lambda pos, player=False: pygame.Vector2(80, 0)
    )
    release_all(monkeypatch)

    player.update(0.1)

    assert player.velocity.x == pytest.approx(
        80.0 * 0.1 * math.exp(-PLAYER_LINEAR_DAMPING * 0.1)
    )
    assert player.position.x == pytest.approx(640 + player.velocity.x * 0.1)


# --- Wrap ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "start_x, start_y, expected_x, expected_y",
    [
        # right -> left
        (SCREEN_WIDTH + PLAYER_RADIUS + 5, SCREEN_HEIGHT / 2,
         -PLAYER_RADIUS, SCREEN_HEIGHT / 2),
        # left -> right
        (-PLAYER_RADIUS - 5, SCREEN_HEIGHT / 2,
         SCREEN_WIDTH + PLAYER_RADIUS, SCREEN_HEIGHT / 2),
        # top -> bottom
        (SCREEN_WIDTH / 2, -PLAYER_RADIUS - 5,
         SCREEN_WIDTH / 2, SCREEN_HEIGHT + PLAYER_RADIUS),
        # bottom -> top
        (SCREEN_WIDTH / 2, SCREEN_HEIGHT + PLAYER_RADIUS + 5,
         SCREEN_WIDTH / 2, -PLAYER_RADIUS),
    ],
)
def test_wrap_reenters_the_opposite_side(
    monkeypatch, start_x, start_y, expected_x, expected_y
):
    """The ship is the one body that wraps: crossing fully past an edge
    re-enters the other side at the hull-radius margin. Rocks cull instead
    — tests/test_culling.py pins that."""
    pygame.init()
    player = Player(start_x, start_y)
    player.velocity.update((0, 0))
    release_all(monkeypatch)

    player.update(1 / 60)

    assert player.position.x == pytest.approx(expected_x)
    assert player.position.y == pytest.approx(expected_y)


def test_wrap_never_tunnels_past_huge_overshoot(monkeypatch):
    """The wrap is an if/elif on the margin, not a modulo: any overshoot,
    however far, lands back inside."""
    pygame.init()
    player = Player(200000, 360)
    player.velocity.update((0, 0))
    release_all(monkeypatch)

    player.update(1 / 60)

    assert player.position.x == pytest.approx(-PLAYER_RADIUS)


def test_a_ship_inside_the_wrap_margin_stays_put(monkeypatch):
    """The hull radius is the margin: a ship still touching the screen
    does not teleport."""
    pygame.init()
    player = Player(SCREEN_WIDTH + PLAYER_RADIUS - 1, SCREEN_HEIGHT / 2)
    player.velocity.update((0, 0))
    release_all(monkeypatch)

    player.update(1 / 60)

    assert player.position.x == pytest.approx(SCREEN_WIDTH + PLAYER_RADIUS - 1)


# --- Frozen frames ------------------------------------------------------------


def test_a_frozen_frame_integrates_nothing(monkeypatch):
    """dt = 0 (hit-stop, pause): no thrust, no damping, no pull, no
    cooldown ticks — the ship neither creeps nor cools."""
    pygame.init()
    player = Player(640, 360)
    player.dash()
    press(monkeypatch, pygame.K_w)
    before = (
        player.position.copy(),
        player.velocity.copy(),
        player.dash_timer,
        player.invulnerability_timer,
        player.shot_cooldown_timer,
    )
    monkeypatch.setattr(
        blackhole, "pull_at", lambda pos, player=False: pygame.Vector2(80, 0)
    )

    player.update(0.0)

    assert player.position == before[0]
    assert player.velocity == before[1]
    assert player.dash_timer == pytest.approx(before[2])
    assert player.invulnerability_timer == pytest.approx(before[3])
    assert player.shot_cooldown_timer == pytest.approx(before[4])
