"""Tests for wave progression (engagement F3): the pure wave_params math,
the guarded advance in main's loop, the once-per-wave milestone event, and
the WAVE n banner."""

import json

import pygame
import pytest

import asteroidfield
from asteroid import Asteroid
from asteroidfield import AsteroidField, wave_params
from constants import (
    ASTEROID_SPAWN_RATE_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    WAVE_BANNER_SECONDS,
    WAVE_SPAWN_INTERVAL_FLOOR,
)
from game import Game
from hud import WaveBanner
from main import maybe_advance_wave
from player import Player
from shot import Shot


def make_world(tmp_path):
    """Fresh groups + Game + field wired like main(), saving into tmp_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = updatable

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    return game, field, asteroids, updatable, drawable


def populate(field):
    """A real spawn, as the field's update() makes one: joins the group and
    raises the populated guard, without update()'s randomness."""
    return field.spawn(60, pygame.Vector2(100, 100), pygame.Vector2(10, 0))


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def wave_started_events(tmp_path):
    return [e for e in read_events(tmp_path) if e["type"] == "wave_started"]


# --- wave_params: pure difficulty math ---


def test_wave_params_wave_one_is_the_untuned_baseline():
    """Wave 1 must reproduce the pre-F3 field exactly: 0.8s cadence, 40–100."""
    params = wave_params(1)

    assert params["spawn_interval"] == ASTEROID_SPAWN_RATE_SECONDS
    assert params["speed_min"] == 40
    assert params["speed_max"] == 100


def test_wave_params_tightens_interval_and_shifts_speed_band():
    two = wave_params(2)
    assert two["spawn_interval"] == pytest.approx(ASTEROID_SPAWN_RATE_SECONDS * 0.9)
    assert two["speed_min"] == 50
    assert two["speed_max"] == 115

    three = wave_params(3)
    assert three["spawn_interval"] == pytest.approx(ASTEROID_SPAWN_RATE_SECONDS * 0.9**2)
    assert three["speed_min"] == 60
    assert three["speed_max"] == 130


def test_wave_params_interval_floors_at_three_tenths():
    # 0.8 * 0.9**9 ≈ 0.310 — still above the floor; 0.8 * 0.9**10 ≈ 0.279 is
    # the first wave clamped to it, and every wave after stays there.
    assert wave_params(10)["spawn_interval"] == pytest.approx(0.8 * 0.9**9)
    assert wave_params(10)["spawn_interval"] > WAVE_SPAWN_INTERVAL_FLOOR
    assert wave_params(11)["spawn_interval"] == WAVE_SPAWN_INTERVAL_FLOOR
    assert wave_params(50)["spawn_interval"] == WAVE_SPAWN_INTERVAL_FLOOR


def test_wave_params_speed_band_stays_valid_ever_after():
    """speed_max must stay above speed_min or random.randint raises."""
    for wave in range(1, 60):
        params = wave_params(wave)
        assert params["speed_min"] < params["speed_max"]


# --- the guarded advance (main.maybe_advance_wave) ---


def test_empty_field_at_game_start_does_not_advance(tmp_path):
    """The trap: at start the field is empty and wave is 1 — without the
    populated guard the counter would immediately tick to 2."""
    pygame.init()
    game, field, *_ = make_world(tmp_path)
    banner = WaveBanner()

    maybe_advance_wave(game, field, banner)

    assert game.wave == 1
    assert wave_started_events(tmp_path) == []


def test_wave_advances_when_populated_field_is_cleared(tmp_path):
    pygame.init()
    game, field, asteroids, *_ = make_world(tmp_path)
    banner = WaveBanner()
    asteroid = populate(field)
    field.spawn_timer = 0.5  # a stale clock the advance must reset
    assert len(asteroids) == 1

    asteroid.kill()  # what split()/culling do to the last rock
    maybe_advance_wave(game, field, banner)

    assert game.wave == 2
    assert field.spawn_timer == 0.0
    events = wave_started_events(tmp_path)
    assert len(events) == 1
    assert events[0]["wave"] == 2


def test_wave_started_emitted_exactly_once_per_wave(tmp_path):
    pygame.init()
    game, field, *_ = make_world(tmp_path)
    banner = WaveBanner()

    for expected_wave in (2, 3):
        populate(field).kill()
        maybe_advance_wave(game, field, banner)
        maybe_advance_wave(game, field, banner)  # same state: must not re-fire
        assert game.wave == expected_wave

    assert [e["wave"] for e in wave_started_events(tmp_path)] == [2, 3]


def test_no_advance_while_asteroids_remain(tmp_path):
    pygame.init()
    game, field, *_ = make_world(tmp_path)
    populate(field)  # alive in the group: the wave is not cleared

    maybe_advance_wave(game, field, WaveBanner())

    assert game.wave == 1
    assert wave_started_events(tmp_path) == []


def test_no_advance_during_game_over(tmp_path):
    pygame.init()
    game, field, *_ = make_world(tmp_path)
    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"
    populate(field).kill()  # even a cleared populated field must not advance

    maybe_advance_wave(game, field, WaveBanner())

    assert game.wave == 1
    assert wave_started_events(tmp_path) == []


def test_start_wave_resets_the_clock_and_the_guard(tmp_path):
    pygame.init()
    game, field, *_ = make_world(tmp_path)
    field.spawn_timer = 5.0
    populate(field)

    field.start_wave()

    assert field.spawn_timer == 0.0
    assert field.spawned_this_wave == 0


def test_restart_does_not_phantom_advance(tmp_path):
    """After R-restart the field is empty and wave is 1; main's event pump
    resets the field alongside the game, and the guard must hold wave at 1
    until the fresh run spawns."""
    pygame.init()
    game, field, *_ = make_world(tmp_path)
    populate(field)
    for _ in range(3):
        game.player_hit()

    game.restart()
    field.start_wave()  # what main's event pump does alongside game.restart()
    maybe_advance_wave(game, field, WaveBanner())

    assert game.wave == 1
    assert wave_started_events(tmp_path) == []


# --- the field consumes wave_params ---


def test_field_spawns_use_the_wave_speed_band(tmp_path, monkeypatch):
    pygame.init()
    game, field, asteroids, *_ = make_world(tmp_path)
    game.wave = 3
    captured = []

    def fake_randint(low, high):
        captured.append((low, high))
        return low

    monkeypatch.setattr(asteroidfield.random, "randint", fake_randint)

    field.update(1.0)  # far past wave 3's ~0.648s interval: exactly one spawn

    # The speed band is the update()'s first randint; rotate and kind follow.
    assert captured[0] == (60, 130)
    assert len(asteroids) == 1


def test_field_spawn_cadence_uses_the_wave_interval(tmp_path):
    pygame.init()
    game, field, asteroids, *_ = make_world(tmp_path)
    game.wave = 2  # interval 0.8 * 0.9 = 0.72s

    field.update(0.5)  # below the interval: nothing yet
    assert len(asteroids) == 0

    field.update(0.3)  # timer 0.8 > 0.72: the spawn fires
    assert len(asteroids) == 1


# --- the WAVE n banner ---


def test_banner_flash_fades_on_the_dt_timer():
    banner = WaveBanner()
    assert not banner.visible

    banner.show(2)
    assert banner.visible
    assert banner.wave == 2

    banner.update(WAVE_BANNER_SECONDS / 2)
    assert banner.visible  # halfway through the flash

    banner.update(WAVE_BANNER_SECONDS)  # past the end
    assert not banner.visible
    banner.update(WAVE_BANNER_SECONDS)  # and it never goes negative
    assert banner.timer == 0.0


def test_banner_paints_centered_pixels_headless():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    banner = WaveBanner()
    banner.show(3)

    screen.fill("black")
    banner.draw(screen)
    center_x, center_y = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 3
    samples = [
        screen.get_at((x, y))
        for x in range(center_x - 200, center_x + 200, 8)
        for y in range(center_y - 40, center_y + 40, 4)
    ]
    assert any(pixel != (0, 0, 0, 255) for pixel in samples)
