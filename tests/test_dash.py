"""Insanity core: the dash — cooldown gate, an impulse that composes with
the ship's carried momentum (physics overhaul), i-frames via max(), and
the combo-breaking wiring in main.

Failure signatures the tests must catch (spec): a dash that fires on
cooldown, i-frames that shorten a respawn grace, a dash that replaces or
hard-zeroes the ship's momentum instead of composing with it, and a dash
that leaves the combo intact.
"""

import json
import math

import pygame
import pytest

from constants import (
    DASH_COOLDOWN_S,
    DASH_DECAY_S,
    DASH_IMPULSE,
    DASH_IFRAME_S,
    PLAYER_INVULNERABILITY_SECONDS,
    PLAYER_LINEAR_DAMPING,
    PLAYER_MAX_SPEED,
)
from game import Game
from main import try_dash
from player import Player


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def make_world(tmp_path):
    """A Game wired to a real player and groups, saving into tmp_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    Player.containers = (updatable, drawable)
    player = Player(100, 660)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, powerups


def run_seconds(player, seconds, dt=1 / 60):
    """Advance the player's own update loop (no keys held) by a duration."""
    frames = round(seconds / dt)
    for _ in range(frames):
        player.update(dt)


def test_dash_impulses_along_the_nose():
    pygame.init()
    player = Player(100, 660)

    assert player.dash() is True
    # rotation 0 → the nose is (0, 1) rotated by it: the impulse rides the
    # same forward vector the triangle and shots use.
    expected = pygame.Vector2(0, 1).rotate(player.rotation) * DASH_IMPULSE
    assert player.velocity == expected


def test_dash_composes_with_carried_momentum():
    """The impulse adds to whatever the ship carries (physics overhaul):
    thrust momentum plus dash — and the update step's shared ceiling
    clamps the sum on the next integration."""
    pygame.init()
    player = Player(100, 660)
    nose = pygame.Vector2(0, 1).rotate(player.rotation)
    player.velocity = nose * 100.0  # carried thrust momentum

    assert player.dash() is True
    assert player.velocity == nose * (100.0 + DASH_IMPULSE)

    player.update(1 / 60)
    assert player.velocity.length() == pytest.approx(PLAYER_MAX_SPEED)


def test_dash_respects_the_cooldown_then_recovers(tmp_path):
    pygame.init()
    player = Player(100, 660)

    assert player.dash() is True
    assert player.dash() is False  # cooling down: no second impulse
    assert player.dash_timer == pytest.approx(DASH_COOLDOWN_S)

    run_seconds(player, DASH_COOLDOWN_S + 0.1)
    assert player.dash_timer == 0.0  # fully cooled
    # No clean handback: the glide's momentum persists — damped, not
    # zeroed. Damping, not the cooldown, is what returns normal handling.
    assert 0 < player.velocity.length() < DASH_IMPULSE
    assert player.dash() is True  # the panic button is back


def test_dash_iframes_never_shorten_a_respawn_grace():
    pygame.init()
    player = Player(100, 660)
    player.dash()
    assert player.invulnerability_timer == pytest.approx(DASH_IFRAME_S)

    # The respawn grace is longer than the dash i-frames: dashing during
    # it must keep the longer window, never clip it.
    player.dash_timer = 0.0
    player.invulnerability_timer = PLAYER_INVULNERABILITY_SECONDS
    player.dash()
    assert player.invulnerability_timer == pytest.approx(
        PLAYER_INVULNERABILITY_SECONDS
    )


def test_glide_decays_under_the_shared_damping():
    pygame.init()
    player = Player(100, 660)
    player.dash()
    start = player.velocity.length()
    assert start == pytest.approx(DASH_IMPULSE)

    # The visible glide bleeds off under the same linear damping every
    # velocity obeys now (physics overhaul — the dash owns no decay of its
    # own): after DASH_DECAY_S the glide keeps exactly the damping
    # fraction, and it is still gliding.
    run_seconds(player, DASH_DECAY_S)
    assert player.velocity.length() == pytest.approx(
        start * math.exp(-PLAYER_LINEAR_DAMPING * DASH_DECAY_S)
    )


def test_a_frozen_frame_neither_ticks_nor_decays_the_glide():
    pygame.init()
    player = Player(100, 660)
    player.dash()
    before = (player.dash_timer, player.velocity.length())

    player.update(0.0)  # a hit-stop frame steps dt=0

    assert player.dash_timer == pytest.approx(before[0])
    assert player.velocity.length() == pytest.approx(before[1])


def test_successful_dash_breaks_the_combo_and_logs(tmp_path):
    pygame.init()
    game, player, *_ = make_world(tmp_path)
    for _ in range(2):
        game.register_kill(100)
    assert game.combo.chain == 2

    assert try_dash(player, game) is True
    assert game.combo.chain == 0  # the panic button prices its i-frames
    assert sum(e["type"] == "dash_used" for e in read_events(tmp_path)) == 1


def test_a_cooled_out_dash_does_not_break_anything(tmp_path):
    """A failed dash (on cooldown) neither re-breaks the chain nor logs."""
    pygame.init()
    game, player, *_ = make_world(tmp_path)

    assert try_dash(player, game) is True  # the first dash fires
    for _ in range(2):
        game.register_kill(100)  # rebuild a chain during the cooldown
    assert game.combo.chain == 2

    assert try_dash(player, game) is False  # cooling down
    assert game.combo.chain == 2  # untouched
    assert sum(e["type"] == "dash_used" for e in read_events(tmp_path)) == 1
