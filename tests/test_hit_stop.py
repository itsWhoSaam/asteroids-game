"""Insanity core: the hit-stop freeze — request semantics, the pure dt
gate, and the sweep wiring that buys a beat per destruction.

Failure signatures the tests must catch (spec): a frozen frame that never
thaws; a freeze shortened by a later, smaller request; the multi beat
mispriced for single kills.
"""

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    HIT_STOP_BASE_S,
    HIT_STOP_MULTI_SCALE,
    HIT_STOP_MULTI_S,
    SCREEN_WIDTH,
)
from game import Game
from main import HitStop, effective_frame_dt, freeze_for_destructions, handle_collisions
from player import Player
from shot import Shot


def make_world(tmp_path):
    """A Game wired to a real player and groups, saving into tmp_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    player = Player(100, 660)  # far from the rocks: no player hit
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, powerups


# --- HitStop semantics --------------------------------------------------------


def test_freeze_defaults_to_the_base_beat():
    hs = HitStop()
    assert not hs.frozen
    assert hs.remaining == 0.0

    hs.freeze()
    assert hs.remaining == pytest.approx(HIT_STOP_BASE_S)
    assert hs.frozen


def test_the_multi_scale_prices_the_multi_beat():
    hs = HitStop()
    hs.freeze(HIT_STOP_MULTI_SCALE)
    assert hs.remaining == pytest.approx(HIT_STOP_MULTI_S)


def test_the_longest_request_wins_and_nothing_shortens_a_freeze():
    hs = HitStop()
    hs.freeze(HIT_STOP_MULTI_SCALE)  # multi first
    hs.freeze()  # a later base request must not shorten the running freeze
    assert hs.remaining == pytest.approx(HIT_STOP_MULTI_S)

    hs.update(HIT_STOP_MULTI_S)  # drain past the multi beat
    hs.freeze(HIT_STOP_MULTI_SCALE)  # a fresh long request re-arms
    assert hs.frozen


def test_update_ticks_on_real_dt_and_never_goes_negative():
    hs = HitStop()
    hs.freeze()
    hs.update(HIT_STOP_BASE_S / 2)
    assert hs.frozen  # half-drained
    hs.update(HIT_STOP_BASE_S)
    assert not hs.frozen
    assert hs.remaining == 0.0
    hs.update(10.0)  # an over-long tick clamps at zero, never negative
    assert hs.remaining == 0.0


def test_the_sim_never_stalls_permanently():
    """An absurd request still thaws: the freeze ticks on real dt."""
    hs = HitStop()
    hs.freeze(1000.0)
    dt = 1 / 60
    frames = 0
    while hs.frozen:
        hs.update(dt)
        frames += 1
        assert frames < 60 * 60 * 10  # bounded: the pause always ends
    assert frames == pytest.approx(1000 * HIT_STOP_BASE_S * 60, rel=0.01)


# --- the pure dt gate ---------------------------------------------------------


def test_effective_frame_dt_is_zero_while_frozen():
    hs = HitStop()
    assert effective_frame_dt(1 / 60, hs) == 1 / 60

    hs.freeze()
    assert effective_frame_dt(1 / 60, hs) == 0.0  # the whole sim holds

    hs.update(1.0)
    assert effective_frame_dt(1 / 60, hs) == 1 / 60  # thawed


def test_freeze_for_destructions_prices_the_count():
    hs = HitStop()
    freeze_for_destructions(hs, 0)  # a cull or a whiff buys nothing
    assert not hs.frozen

    freeze_for_destructions(hs, 1)
    assert hs.remaining == pytest.approx(HIT_STOP_BASE_S)

    hs.update(HIT_STOP_BASE_S)
    freeze_for_destructions(hs, 3)
    assert hs.remaining == pytest.approx(HIT_STOP_MULTI_S)

    freeze_for_destructions(None, 1)  # a caller without a freeze: no crash


# --- sweep wiring -------------------------------------------------------------


def test_one_shot_kill_requests_the_base_beat(tmp_path):
    pygame.init()
    game, player, asteroids, shots, powerups = make_world(tmp_path)
    hs = HitStop()

    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 3)
    Shot(640, 360)
    handle_collisions(asteroids, shots, player, game, powerups, hit_stop=hs)

    assert hs.remaining == pytest.approx(HIT_STOP_BASE_S)


def test_several_shot_kills_in_one_frame_request_the_multi_beat(tmp_path):
    """Two rocks, two shots, one sweep: the multi beat, not two base beats
    stacked (the longest request wins, and one sweep is one beat)."""
    pygame.init()
    game, player, asteroids, shots, powerups = make_world(tmp_path)
    hs = HitStop()

    Asteroid(200, 200, ASTEROID_MIN_RADIUS * 3)
    Asteroid(800, 300, ASTEROID_MIN_RADIUS * 3)
    Shot(200, 200)
    Shot(800, 300)
    handle_collisions(asteroids, shots, player, game, powerups, hit_stop=hs)

    assert hs.remaining == pytest.approx(HIT_STOP_MULTI_S)


def test_the_sweep_works_without_a_freeze_sink(tmp_path):
    """The pinned five-argument call sites (and the whole prior suite) pass
    no hit_stop — the wiring must stay optional."""
    pygame.init()
    game, player, asteroids, shots, powerups = make_world(tmp_path)

    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 3)
    Shot(640, 360)
    handle_collisions(asteroids, shots, player, game, powerups)  # no hit_stop

    assert game.score > 0  # the kill resolved normally
