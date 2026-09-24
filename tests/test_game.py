"""Tests for the Game run-state object (engagement F2): lives, respawn,
game over, restart."""

import json

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    PLAYER_INVULNERABILITY_SECONDS,
    PLAYER_START_LIVES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from hud import Score, write_save
from player import Player
from shot import Shot


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)

    return updatable, drawable, asteroids, shots


def make_world(tmp_path, save_path=None):
    """A Game wired to a real player and groups, saving into tmp_path."""
    updatable, drawable, asteroids, shots = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    if save_path is None:
        save_path = tmp_path / "game_save.json"
    game = Game(player, asteroids, shots, save_path=save_path)
    return game, player, asteroids, shots, updatable, drawable


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_new_game_starts_at_full_lives_wave_one_playing(tmp_path):
    pygame.init()
    game, *_ = make_world(tmp_path)

    assert game.lives == PLAYER_START_LIVES
    assert game.wave == 1
    assert game.state == "playing"
    assert game.score == 0
    assert game.muted is False


def test_add_score_delegates_to_the_f1_seam(tmp_path):
    """Points flow to the absorbed Score seam: run score rises and the
    high_score_beaten milestone still fires exactly once."""
    pygame.init()
    game, *_ = make_world(tmp_path)

    game.add_score(20)
    game.add_score(50)

    assert game.score == 70
    assert game.high_score == 70
    assert sum(e["type"] == "high_score_beaten" for e in read_events(tmp_path)) == 1


def test_player_hit_costs_one_life_and_respawns_centered(tmp_path):
    pygame.init()
    game, player, *_ = make_world(tmp_path)
    player.position = pygame.Vector2(100, 660)
    player.velocity = pygame.Vector2(120, -40)

    game.player_hit()

    assert game.lives == PLAYER_START_LIVES - 1
    assert game.state == "playing"
    assert player.position == pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    assert player.velocity == pygame.Vector2(0, 0)
    assert player.invulnerable
    assert player.invulnerability_timer == pytest.approx(PLAYER_INVULNERABILITY_SECONDS)


def test_game_over_only_at_zero_lives(tmp_path):
    pygame.init()
    game, *_ = make_world(tmp_path)

    for expected in (2, 1):
        game.player_hit()
        assert game.lives == expected
        assert game.state == "playing"

    game.player_hit()  # the last life
    assert game.lives == 0
    assert game.state == "game_over"


def test_hits_past_zero_lives_are_guarded(tmp_path):
    """Rocks drifting through the dead ship must not re-trigger game over
    or push the counter negative."""
    pygame.init()
    game, *_ = make_world(tmp_path)

    for _ in range(5):
        game.player_hit()

    assert game.lives == 0
    assert game.state == "game_over"
    assert sum(e["type"] == "game_over" for e in read_events(tmp_path)) == 1


def test_game_over_logs_final_score(tmp_path):
    pygame.init()
    game, *_ = make_world(tmp_path)
    game.add_score(120)

    for _ in range(3):
        game.player_hit()

    overs = [e for e in read_events(tmp_path) if e["type"] == "game_over"]
    assert len(overs) == 1
    assert overs[0]["score"] == 120
    assert overs[0]["high_score"] == 120


def test_restart_resets_counters_and_clears_the_world(tmp_path):
    pygame.init()
    game, player, asteroids, shots, updatable, drawable = make_world(tmp_path)
    game.add_score(200)
    for _ in range(3):
        game.player_hit()
    Asteroid(640, 360, 40)
    Asteroid(200, 200, 60)
    Shot(640, 360)
    assert len(asteroids) == 2 and len(shots) == 1

    game.restart()

    assert game.score == 0
    assert game.lives == PLAYER_START_LIVES
    assert game.wave == 1
    assert game.state == "playing"
    assert len(asteroids) == 0
    assert len(shots) == 0
    # No zombies: asteroids live in asteroids AND updatable AND drawable, so
    # clearing one group would leave rocks still updating, rendering, and
    # unshootable — the visible lie the restart must eliminate.
    assert not any(isinstance(s, Asteroid) for s in updatable)
    assert not any(isinstance(s, Asteroid) for s in drawable)
    assert not any(isinstance(s, Shot) for s in updatable)
    assert player.position == pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    assert player.velocity == pygame.Vector2(0, 0)
    assert sum(e["type"] == "restart" for e in read_events(tmp_path)) == 1


def test_restart_rearms_the_high_score_flag_but_keeps_the_record(tmp_path):
    pygame.init()
    game, *_ = make_world(tmp_path)
    game.add_score(500)  # beats the default high score of 0
    assert game.new_high

    for _ in range(3):
        game.player_hit()
    game.restart()

    assert not game.new_high  # the flag is re-armed for the fresh run
    assert game.high_score == 500  # but the record itself survives
    game.add_score(501)  # a fresh run that beats it again re-fires the milestone
    assert sum(e["type"] == "high_score_beaten" for e in read_events(tmp_path)) == 2


def test_new_high_flag_stays_false_when_record_not_beaten(tmp_path):
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 900, "muted": False})
    pygame.init()
    game, *_ = make_world(tmp_path, save_path=path)

    game.add_score(100)
    for _ in range(3):
        game.player_hit()

    assert game.state == "game_over"
    assert not game.new_high
    assert game.score < game.high_score


def test_score_reset_starts_fresh_run_keeping_high(tmp_path):
    """Score.reset is the seam Game.restart uses: zero the run, keep the record."""
    pygame.init()
    score = Score(tmp_path / "game_save.json")
    score.add_score(300)
    assert score.beaten

    score.reset()

    assert score.current == 0
    assert not score.beaten
    assert score.high == 300
