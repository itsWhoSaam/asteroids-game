"""Shared test setup: headless pygame and a pristine logger for every test."""

import os

# Set before any test module imports pygame so the suite runs on machines
# with no display (CI, sandboxes). setdefault keeps explicit overrides working.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

import logger


@pytest.fixture(autouse=True)
def fresh_logger(tmp_path, monkeypatch):
    """Redirect logger output into tmp_path and reset per-run state."""
    monkeypatch.setattr(logger, "_STATE_LOG_PATH", str(tmp_path / "game_state.jsonl"))
    monkeypatch.setattr(logger, "_EVENT_LOG_PATH", str(tmp_path / "game_events.jsonl"))
    monkeypatch.setattr(logger, "_frame_count", 0)
    monkeypatch.setattr(logger, "_state_log_initialized", False)
    monkeypatch.setattr(logger, "_event_log_initialized", False)
