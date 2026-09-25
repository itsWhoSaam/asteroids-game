"""Tests for the Tier 1 pause: a paused flag gates the whole simulation
step, the overlay draws headless, and pause only ever engages in play."""

import json

import pygame
import pytest

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import (
    ASTEROID_MIN_RADIUS,
    PAUSE_OVERLAY_DIM_ALPHA,
    PAUSE_OVERLAY_DIM_COLOR,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    WAVE_BANNER_SECONDS,
)
from drones import DroneBay
from economy import Economy
from game import Game
from hud import WaveBanner, draw_pause
from main import update_world
from particles import Shake
from player import Player
from shot import Shot


def make_world(tmp_path):
    """A Game plus every real object update_world touches, saving to tmp_path."""
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
    economy = Economy(save_path=tmp_path / "idle_save.json")
    drones = DroneBay(economy)
    return game, player, asteroids, shots, updatable, field, drones, economy


def event_types(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["type"] for line in path.read_text().splitlines()]


def test_pause_only_engages_during_play(tmp_path):
    """The gate: a live run toggles freely; the game-over screen refuses."""
    pygame.init()
    game, *_ = make_world(tmp_path)

    # A fresh run pauses and resumes through the same toggle.
    assert game.paused is False
    assert game.toggle_pause() is True
    assert game.paused is True
    assert game.toggle_pause() is True
    assert game.paused is False

    # At game over the overlay owns the screen — pause keys are refused.
    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"
    assert game.toggle_pause() is False
    assert game.paused is False


def test_paused_flag_gates_update_world(tmp_path):
    """The core contract: a frozen frame advances nothing. The same call
    that moves a rock mid-play holds the world perfectly still while
    game.paused — sprites included, which is what gates updatable.update."""
    pygame.init()
    game, player, asteroids, shots, updatable, field, drones, economy = make_world(
        tmp_path
    )
    rock = Asteroid(120, 120, ASTEROID_MIN_RADIUS)
    rock.velocity = pygame.Vector2(120, -40)
    banner = WaveBanner()
    shake = Shake()

    start = pygame.Vector2(rock.position)
    for _ in range(2):
        update_world(updatable, drones, asteroids, shots, player, game,
                     [], shake, field, banner, economy, 1 / 60)
    assert rock.position != start  # unpaused control: the world moves

    game.paused = True
    frozen = pygame.Vector2(rock.position)
    for _ in range(2):
        update_world(updatable, drones, asteroids, shots, player, game,
                     [], shake, field, banner, economy, 1 / 60)
    assert rock.position == frozen  # the frame held completely still


def test_frozen_frame_holds_every_timer(tmp_path):
    """Pause freezes the clocks too: the wave banner, bought-powerup
    durations, and the shake decay all hold while the overlay is up."""
    pygame.init()
    game, player, asteroids, shots, updatable, field, drones, economy = make_world(
        tmp_path
    )
    banner = WaveBanner()
    banner.show(2)
    economy.powerup_timers["chrono"] = 5.0
    shake = Shake()
    shake.kick(10.0)

    game.paused = True
    update_world(updatable, drones, asteroids, shots, player, game,
                 [], shake, field, banner, economy, 1 / 60)

    assert banner.timer == WAVE_BANNER_SECONDS
    assert economy.powerup_timers["chrono"] == 5.0
    assert shake.magnitude == 10.0


def test_restart_clears_the_pause_flag(tmp_path):
    """Both restart hooks (game-over R, pause-overlay R) funnel through
    Game.restart — a fresh run is always live and unpaused."""
    pygame.init()
    game, *_ = make_world(tmp_path)
    game.toggle_pause()
    assert game.paused is True

    game.restart()

    assert game.paused is False
    assert game.state == "playing"


def test_game_over_never_carries_a_pause(tmp_path):
    """The game-over screen is unaffected by pause: the state flip clears
    the flag, so the pause overlay can never dim a dead run."""
    pygame.init()
    game, *_ = make_world(tmp_path)
    game.toggle_pause()
    assert game.paused is True

    game.game_over()

    assert game.state == "game_over"
    assert game.paused is False


def test_mute_still_toggles_while_paused(tmp_path):
    """Spec contract: mute works while paused — the M handler is not run
    state and never consults the pause flag."""
    pygame.init()
    game, *_ = make_world(tmp_path)
    game.toggle_pause()
    assert game.paused is True

    assert game.toggle_mute() is True
    assert game.muted is True
    assert game.paused is True  # muting never unpauses


def test_toggle_pause_logs_paused_and_resumed(tmp_path):
    """The event log records the freeze and the resume for run analytics."""
    pygame.init()
    game, *_ = make_world(tmp_path)

    game.toggle_pause()
    game.toggle_pause()

    assert event_types(tmp_path).count("paused") == 1
    assert event_types(tmp_path).count("resumed") == 1


def test_pause_overlay_render_smoke():
    """The overlay draws headless: the dim sheet blends over a white frame
    (surface alpha only — per-pixel alpha would break the dummy driver)."""
    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()

    screen.fill((255, 255, 255))
    draw_pause(screen)  # smoke: must not raise under dummy drivers

    # A corner far from any text is the dim-over-white blend, not white.
    share = PAUSE_OVERLAY_DIM_ALPHA / 255
    corner = screen.get_at((SCREEN_WIDTH - 20, SCREEN_HEIGHT - 20))[:3]
    expected = tuple(
        round(PAUSE_OVERLAY_DIM_COLOR[i] * share + 255 * (1 - share))
        for i in range(3)
    )
    assert corner != (255, 255, 255)
    assert all(abs(corner[i] - expected[i]) <= 2 for i in range(3))
