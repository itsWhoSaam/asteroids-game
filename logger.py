import inspect
import json
import math
import sys
import uuid
from datetime import datetime

__all__ = ["log_state", "log_event"]

_FPS = 60
_MAX_SECONDS = 16
_SPRITE_SAMPLE_LIMIT = 10  # Maximum number of sprites to log per group

_STATE_LOG_PATH = "game_state.jsonl"
_EVENT_LOG_PATH = "game_events.jsonl"

_frame_count = 0
_start_time = datetime.now()

# One id per process: with append-mode logs, concatenated runs stay
# distinguishable by slicing on the "session" field.
_session_id = uuid.uuid4().hex


def _append_line(path, line):
    """Append one line to a JSONL log, tolerating I/O failure.

    A read-only cwd or full disk must print a warning, not crash the game.
    """
    try:
        with open(path, "a") as f:
            f.write(line)
    except OSError as exc:
        print(f"[logger] warning: could not write {path}: {exc}", file=sys.stderr)


def log_state():
    global _frame_count

    # Stop logging after `_MAX_SECONDS` seconds
    if _frame_count > _FPS * _MAX_SECONDS:
        return

    # Take a snapshot approx. once per second
    _frame_count += 1
    if _frame_count % _FPS != 0:
        return

    now = datetime.now()

    frame = inspect.currentframe()
    if frame is None:
        return

    frame_back = frame.f_back
    if frame_back is None:
        return

    local_vars = frame_back.f_locals.copy()

    screen_size = []
    game_state = {}

    for key, value in local_vars.items():
        if "pygame" in str(type(value)) and hasattr(value, "get_size"):
            screen_size = value.get_size()

        if hasattr(value, "__class__") and "Group" in value.__class__.__name__:
            sprites_data = []

            for i, sprite in enumerate(value):
                if i >= _SPRITE_SAMPLE_LIMIT:
                    break

                sprite_info = {"type": sprite.__class__.__name__}

                if hasattr(sprite, "position"):
                    sprite_info["pos"] = [
                        round(sprite.position.x, 2),
                        round(sprite.position.y, 2),
                    ]

                if hasattr(sprite, "velocity"):
                    sprite_info["vel"] = [
                        round(sprite.velocity.x, 2),
                        round(sprite.velocity.y, 2),
                    ]

                if hasattr(sprite, "radius"):
                    sprite_info["rad"] = sprite.radius

                if hasattr(sprite, "rotation"):
                    sprite_info["rot"] = round(sprite.rotation, 2)

                sprites_data.append(sprite_info)

            game_state[key] = {"count": len(value), "sprites": sprites_data}

        if len(game_state) == 0 and hasattr(value, "position"):
            sprite_info = {"type": value.__class__.__name__}

            sprite_info["pos"] = [
                round(value.position.x, 2),
                round(value.position.y, 2),
            ]

            if hasattr(value, "velocity"):
                sprite_info["vel"] = [
                    round(value.velocity.x, 2),
                    round(value.velocity.y, 2),
                ]

            if hasattr(value, "radius"):
                sprite_info["rad"] = value.radius

            if hasattr(value, "rotation"):
                sprite_info["rot"] = round(value.rotation, 2)

            game_state[key] = sprite_info

    entry = {
        "timestamp": now.strftime("%H:%M:%S.%f")[:-3],
        "elapsed_s": math.floor((now - _start_time).total_seconds()),
        "frame": _frame_count,
        "session": _session_id,
        "screen_size": screen_size,
        **game_state,
    }

    # Append unconditionally: prior runs' lines survive (each record carries
    # its own session id), replacing the per-run "w" truncation that also
    # let concurrent game instances erase each other's logs.
    _append_line(_STATE_LOG_PATH, json.dumps(entry) + "\n")


def log_event(event_type, **details):
    now = datetime.now()

    event = {
        "timestamp": now.strftime("%H:%M:%S.%f")[:-3],
        "elapsed_s": math.floor((now - _start_time).total_seconds()),
        "frame": _frame_count,
        "session": _session_id,
        "type": event_type,
        **details,
    }

    _append_line(_EVENT_LOG_PATH, json.dumps(event) + "\n")