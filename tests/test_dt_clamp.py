"""Regression tests for the frame-delta clamp (B7)."""

import pytest

from constants import (
    ASTEROID_MIN_RADIUS,
    PLAYER_MAX_SPEED,
    PLAYER_RADIUS,
)
from main import compute_dt


def test_stall_delta_is_clamped():
    """A 5 s stall (window drag, alt-tab) must not become a 5 s step."""
    assert compute_dt(5000) == 0.1


def test_normal_frame_delta_passes_through_unclamped():
    """A 16 ms frame at the 60 FPS target is untouched by the clamp."""
    assert compute_dt(16) == pytest.approx(0.016)


def test_clamped_delta_bounds_single_frame_movement():
    """The ship at its cap moves PLAYER_MAX_SPEED * MAX_DT = 36 px in one
    clamped frame — inside the 40 px minimum contact overlap (player hull
    + smallest rock), so overlap cannot be jumped over. Anti-tunnel by
    arithmetic (physics overhaul: the thrust ceiling pins this margin)."""
    worst_case = PLAYER_MAX_SPEED * compute_dt(5000)
    assert worst_case == pytest.approx(36.0)
    assert worst_case < PLAYER_RADIUS + ASTEROID_MIN_RADIUS
