"""Sanity tests for the JSONL logger, isolated from the repo root."""

import json

import logger


def test_log_event_appends_one_line(tmp_path):
    logger.log_event("test_event", detail="x")

    lines = (tmp_path / "game_events.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["type"] == "test_event"
    assert record["detail"] == "x"
    assert record["frame"] == 0  # fixture reset the frame counter


def test_log_state_writes_one_snapshot_at_sample_boundary(tmp_path):
    logger._frame_count = logger._FPS - 1  # next call hits the 1-second sample

    logger.log_state()

    lines = (tmp_path / "game_state.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["frame"] == logger._FPS


def test_fixture_resets_logger_state_between_tests():
    """Earlier tests in this module initialized the logger; the autouse
    fixture must have restored pristine run-state."""
    assert logger._frame_count == 0
    assert logger._state_log_initialized is False
    assert logger._event_log_initialized is False
