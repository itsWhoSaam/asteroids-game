"""Daily seeded challenge (Tier 3): the date-seeded spawn path, the
per-date best's save-key contract, and the D toggle's mode gating.

The determinism contract is the feature's core: a daily run's field draws
from a fresh RNG seeded with the challenge date, so the same seed replays
the same spawn sequence — timing, positions, velocities, sizes — and a
different date's seed diverges. The save contract rides hud's
read-modify-write merge (the achievements precedent), so the daily_best
key never erases a neighbor. The toggle is selection state: start/game-over
flow only, landing at launch through restart_run.
"""

import datetime
import json
import random

import pygame
import pytest

import challenge
from asteroid import Asteroid
from asteroidfield import AsteroidField, spawn_rng
from challenge import (
    daily_seed,
    daily_slug,
    load_daily_best,
    record_daily_score,
    utc_today,
)
from constants import (
    DAILY_SAVE_KEY,
    DAILY_TAG_ROW,
    HUD_LINE_STEP,
    HUD_MARGIN,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import (
    WaveBanner,
    daily_menu_line,
    draw_hud,
    draw_mode_menu,
    game_over_lines,
)
from main import restart_run
from player import Player
from shot import Shot

DAY = datetime.date(2026, 9, 25)
STEP_DT = 0.5  # half-second frames: wave 1's 2.5 s interval spawns every 5th


def make_world(tmp_path):
    """Fresh groups + Game + field + economy wired like main(), saving into
    tmp_path (the test_waves fixture, plus the ledger restart_run ends run
    effects on)."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = updatable

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    save = tmp_path / "game_save.json"
    game = Game(player, asteroids, shots, save_path=save)
    field = AsteroidField(game)
    economy = Economy(save_path=save)
    return game, field, asteroids, economy, save


# --- date → seed: the purity the whole contract hangs off -------------------


def test_daily_seed_is_the_YYYYMMDD_of_the_date():
    assert daily_seed(DAY) == 20260925


def test_daily_seed_is_stable_within_a_day_and_changes_across_days():
    assert daily_seed(DAY) == daily_seed(datetime.date(2026, 9, 25))
    assert daily_seed(DAY) != daily_seed(datetime.date(2026, 9, 26))


def test_daily_seed_defaults_to_utc_today(monkeypatch):
    fixed = datetime.date(2026, 12, 31)
    monkeypatch.setattr(challenge, "utc_today", lambda: fixed)
    assert daily_seed() == daily_seed(fixed)


def test_daily_slug_is_the_iso_date():
    assert daily_slug(DAY) == "2026-09-25"


def test_utc_today_reads_a_real_date():
    assert isinstance(utc_today(), datetime.date)


# --- the seeded spawn path: same seed, same sequence -------------------------


def spawn_sequence(field, asteroids, frames):
    """(frame, class, radius, x, y, vx, vy) for every spawn the field's
    real update path makes — the full sequence the contract names."""
    sequence = []
    for frame in range(frames):
        before = set(asteroids)
        field.update(STEP_DT)
        for rock in asteroids:
            if rock not in before:
                sequence.append(
                    (frame, type(rock).__name__, rock.radius,
                     rock.position.x, rock.position.y,
                     rock.velocity.x, rock.velocity.y)
                )
    return sequence


def run_seeded_field(tmp_path, seed, frames=400):
    game, field, asteroids, _, _ = make_world(tmp_path)
    field.reseed(seed)
    return spawn_sequence(field, asteroids, frames)


def test_same_seed_replays_the_same_spawn_sequence(tmp_path):
    first = run_seeded_field(tmp_path, daily_seed(DAY))
    assert len(first) >= 10  # the sequence is non-trivial, not one lucky rock

    # Retry the day: same seed, fresh generator, identical spawns —
    # timing (the frame indexes), positions, velocities, sizes, kinds.
    second = run_seeded_field(tmp_path, daily_seed(DAY))
    assert second == first


def test_different_seed_diverges(tmp_path):
    a = run_seeded_field(tmp_path, daily_seed(DAY))
    b = run_seeded_field(tmp_path, daily_seed(datetime.date(2026, 9, 26)))
    assert a != b


def test_spawn_rng_none_returns_the_shared_module_stream():
    assert spawn_rng(None) is random


def test_spawn_rng_seeded_builds_a_fresh_deterministic_generator():
    rng = spawn_rng(daily_seed(DAY))
    assert isinstance(rng, random.Random)
    assert rng.random() == random.Random(daily_seed(DAY)).random()


# --- the save contract: one merge key, per-date slots ------------------------


def test_daily_best_rides_the_merge_contract(tmp_path):
    path = tmp_path / "game_save.json"
    path.write_text(json.dumps({
        "high_score": 77,
        "idle_credits": 12.5,
        "achievements": ["first_nuke"],
        "muted": True,
    }))

    record_daily_score(DAY, 500, path=path)

    data = json.loads(path.read_text())
    assert data["high_score"] == 77
    assert data["idle_credits"] == 12.5
    assert data["achievements"] == ["first_nuke"]
    assert data["muted"] is True
    assert data[DAILY_SAVE_KEY] == {"2026-09-25": 500}


def test_daily_best_keeps_the_best_score_per_date(tmp_path):
    path = tmp_path / "game_save.json"
    assert record_daily_score(DAY, 300, path=path)  # the first run leads
    assert not record_daily_score(DAY, 100, path=path)  # a worse run does not
    assert load_daily_best(DAY, path=path) == 300
    assert record_daily_score(DAY, 900, path=path)  # a better run takes over
    assert load_daily_best(DAY, path=path) == 900


def test_daily_best_slots_are_per_date(tmp_path):
    path = tmp_path / "game_save.json"
    record_daily_score(DAY, 300, path=path)
    other = datetime.date(2026, 9, 26)
    record_daily_score(other, 50, path=path)
    assert load_daily_best(DAY, path=path) == 300
    assert load_daily_best(other, path=path) == 50


def test_missing_or_corrupt_daily_best_reads_zero(tmp_path):
    path = tmp_path / "game_save.json"
    assert load_daily_best(DAY, path=path) == 0  # no file at all
    path.write_text(json.dumps({DAILY_SAVE_KEY: "garbage"}))
    assert load_daily_best(DAY, path=path) == 0
    path.write_text(json.dumps({DAILY_SAVE_KEY: {"2026-09-25": "nope"}}))
    assert load_daily_best(DAY, path=path) == 0


def test_a_zero_score_never_records(tmp_path):
    path = tmp_path / "game_save.json"
    assert not record_daily_score(DAY, 0, path=path)
    assert not path.exists()  # an abandoned run is not a best — no write


# --- the D toggle: selection on the start/game-over flow only ---------------


def test_daily_toggle_only_engages_on_the_start_game_over_flow(tmp_path):
    game, *_ = make_world(tmp_path)
    assert game.daily is False

    game.state = "menu"  # the boot flow: D arms, then disarms
    assert game.toggle_daily() is True
    assert game.daily is True
    assert game.toggle_daily() is True
    assert game.daily is False

    game.state = "playing"  # a live run — even a paused one — refuses D
    game.paused = True
    assert game.toggle_daily() is False
    assert game.daily is False

    game.state = "game_over"  # the end screen offers D again
    assert game.toggle_daily() is True
    assert game.daily is True


def test_daily_selection_survives_both_restart_hooks(tmp_path):
    game, field, asteroids, economy, _ = make_world(tmp_path)
    banner = WaveBanner()
    game.state = "game_over"
    game.toggle_daily()
    restart_run(game, economy, field, banner, asteroids)
    # Selection state, like the mode: restart() lands the run, not the toggle
    # — the game-over R replays today's seeded run instead of dropping it.
    assert game.daily is True


# --- launch wiring: restart_run stamps the date and seeds the field ---------


def test_restart_run_seeds_a_daily_field_from_its_challenge_date(
        tmp_path, monkeypatch):
    game, field, asteroids, economy, _ = make_world(tmp_path)
    monkeypatch.setattr("main.utc_today", lambda: DAY)
    game.daily = True

    restart_run(game, economy, field, WaveBanner(), asteroids)

    assert game.daily_day == DAY
    # The field draws from a fresh generator seeded with the challenge
    # date's seed — the exact stream the determinism tests pin.
    assert field.rng.random() == random.Random(daily_seed(DAY)).random()
    assert game.state == "playing"


def test_restart_run_returns_a_normal_field_to_the_shared_stream(tmp_path):
    game, field, asteroids, economy, _ = make_world(tmp_path)
    field.reseed(daily_seed(DAY))  # poison: a daily generator from before

    restart_run(game, economy, field, WaveBanner(), asteroids)

    assert game.daily is False
    assert game.daily_day is None
    assert field.rng is random


def test_a_daily_retry_replays_the_same_draws(tmp_path, monkeypatch):
    game, field, asteroids, economy, _ = make_world(tmp_path)
    monkeypatch.setattr("main.utc_today", lambda: DAY)
    game.daily = True

    restart_run(game, economy, field, WaveBanner(), asteroids)
    first = field.rng.random()
    field.rng.random()  # burn draws, as a played run would
    field.rng.random()

    restart_run(game, economy, field, WaveBanner(), asteroids)  # the R retry
    assert field.rng.random() == first


# --- the run's end: the day's best records through the merge ----------------


def test_game_over_records_the_daily_best_against_the_run_date(tmp_path):
    game, field, asteroids, _, save = make_world(tmp_path)
    game.state = "playing"
    game.daily = True
    game.daily_day = DAY
    game.add_score(420)

    game.game_over()

    assert load_daily_best(DAY, path=save) == 420
    assert game.daily_best == 420


def test_a_worse_daily_run_does_not_lower_the_best(tmp_path):
    path = tmp_path / "game_save.json"
    record_daily_score(DAY, 900, path=path)
    game, *_ = make_world(tmp_path)
    game.state = "playing"
    game.daily = True
    game.daily_day = DAY
    game.add_score(420)

    game.game_over()

    assert load_daily_best(DAY, path=path) == 900
    assert game.daily_best == 900  # the cached readout keeps the day's best


def test_a_normal_run_records_no_daily_best(tmp_path):
    game, *_ = make_world(tmp_path)
    game.state = "playing"
    game.add_score(420)

    game.game_over()

    assert DAILY_SAVE_KEY not in json.loads(
        (tmp_path / "game_save.json").read_text()
    )


# --- the mode's surfaces: menu row, prompt, HUD tag --------------------------


def test_daily_menu_line_names_the_key_the_best_and_the_state():
    line = daily_menu_line(False, 120)
    assert line.startswith("D  DAILY CHALLENGE")
    assert "best 120" in line
    assert "< on" not in line
    assert "< on" in daily_menu_line(True, 120)


def test_daily_menu_line_reads_the_persisted_best(tmp_path):
    path = tmp_path / "game_save.json"
    record_daily_score(DAY, 777, path=path)
    assert "best 777" in daily_menu_line(True, load_daily_best(DAY, path=path))


def test_game_over_prompt_advertises_the_daily_toggle():
    lines = game_over_lines(500, False, "hard")
    assert lines[-1] == "R restart - 1/2/3 mode (HARD) - D daily - Q quit"
    # The no-mode prompt (the pre-difficulty shape) stays untouched.
    assert game_over_lines(500, False)[-1] == "press R to restart, Q to quit"


def daily_tag_band():
    """The top-right row region where the DAILY CHALLENGE tag seats."""
    return [
        (x, HUD_MARGIN + DAILY_TAG_ROW * HUD_LINE_STEP + dy)
        for x in range(SCREEN_WIDTH - 260, SCREEN_WIDTH - HUD_MARGIN)
        for dy in range(0, 30)
    ]


def test_hud_daily_tag_absent_while_the_mode_is_off():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    paper = (*PALETTE["paper"], 255)

    screen.fill(PALETTE["paper"])
    draw_hud(screen, 0)
    assert all(screen.get_at(pos) == paper for pos in daily_tag_band())


def test_hud_daily_tag_marks_the_mode_in_gold():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    screen.fill(PALETTE["paper"])
    draw_hud(screen, 0, daily=True)

    expected = (*PALETTE["daily_gold"], 255)
    assert any(screen.get_at(pos) == expected for pos in daily_tag_band())


def test_mode_menu_renders_with_the_daily_row_headless():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen.fill(PALETTE["paper"])

    # Off and on both render — the row is drawn text, no per-pixel alpha,
    # so the dummy drivers stay safe (the help-overlay contract).
    draw_mode_menu(screen, "normal", {"normal": 10}, daily=False, daily_best=0)
    draw_mode_menu(screen, "normal", {"normal": 10}, daily=True, daily_best=77)
