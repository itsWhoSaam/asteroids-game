"""Sanity tests for the JSONL logger, isolated from the repo root."""

import json
import uuid

import pytest

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
    assert len(logger._session_id) == 32  # fresh uuid4 hex per test


@pytest.fixture
def read_only_dir(tmp_path):
    """A directory that cannot be written to (restored so pytest can prune)."""
    ro = tmp_path / "read_only"
    ro.mkdir()
    ro.chmod(0o500)
    yield ro
    ro.chmod(0o700)


def test_log_state_survives_read_only_dir(read_only_dir, monkeypatch, capsys):
    """B4: an unwritable log location prints a warning instead of crashing."""
    monkeypatch.setattr(logger, "_STATE_LOG_PATH", str(read_only_dir / "game_state.jsonl"))
    logger._frame_count = logger._FPS - 1  # next call takes a snapshot

    logger.log_state()  # must not raise OSError

    captured = capsys.readouterr()
    assert "warning" in (captured.err + captured.out).lower()
    assert not (read_only_dir / "game_state.jsonl").exists()


def test_log_event_survives_read_only_dir(read_only_dir, monkeypatch, capsys):
    """B4: the event write path is equally fail-safe on I/O errors."""
    monkeypatch.setattr(logger, "_EVENT_LOG_PATH", str(read_only_dir / "game_events.jsonl"))

    logger.log_event("player_hit")  # must not raise OSError

    captured = capsys.readouterr()
    assert "warning" in (captured.err + captured.out).lower()
    assert not (read_only_dir / "game_events.jsonl").exists()


def test_session_id_is_stable_within_a_run(tmp_path):
    """B5: every record of one process carries the same session id."""
    logger.log_event("first")
    logger._frame_count = logger._FPS - 1
    logger.log_state()

    events = [
        json.loads(line)
        for line in (tmp_path / "game_events.jsonl").read_text().splitlines()
    ]
    states = [
        json.loads(line)
        for line in (tmp_path / "game_state.jsonl").read_text().splitlines()
    ]

    assert {record["session"] for record in events + states} == {logger._session_id}


def test_append_across_runs_keeps_prior_lines(tmp_path, monkeypatch):
    """B5: a second run appends to both logs instead of truncating them,
    and its records carry a distinct session id."""
    logger._frame_count = logger._FPS - 1
    logger.log_state()
    logger.log_event("first_run")

    # Simulate a fresh process against the same files: raising=False so the
    # suite also exercises the pre-append-era flags if they exist.
    monkeypatch.setattr(logger, "_session_id", uuid.uuid4().hex, raising=False)
    monkeypatch.setattr(logger, "_event_log_initialized", False, raising=False)
    monkeypatch.setattr(logger, "_state_log_initialized", False, raising=False)

    logger._frame_count = 2 * logger._FPS - 1
    logger.log_state()
    logger.log_event("second_run")

    state_lines = (tmp_path / "game_state.jsonl").read_text().splitlines()
    event_lines = (tmp_path / "game_events.jsonl").read_text().splitlines()

    assert len(state_lines) == 2  # unpatched code truncates to 1
    assert len(event_lines) == 2

    state_first, state_second = (json.loads(line) for line in state_lines)
    event_first, event_second = (json.loads(line) for line in event_lines)
    assert state_first["session"] != state_second["session"]
    assert event_first["session"] != event_second["session"]
