"""Regression tests for the frame-delta clamp (B7)."""

import pytest

from main import compute_dt


def test_stall_delta_is_clamped():
    """A 5 s stall (window drag, alt-tab) must not become a 5 s step."""
    assert compute_dt(5000) == 0.1


def test_normal_frame_delta_passes_through_unclamped():
    """A 16 ms frame at the 60 FPS target is untouched by the clamp."""
    assert compute_dt(16) == pytest.approx(0.016)


def test_clamped_delta_bounds_single_frame_movement():
    """Asteroid at 100 px/s moves <= 10 px in one clamped frame — well under
    the 40 px asteroid+player overlap threshold, so overlap cannot be
    jumped over."""
    assert 100 * compute_dt(5000) <= 10
