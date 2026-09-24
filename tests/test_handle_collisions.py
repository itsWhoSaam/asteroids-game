"""Regression tests for the collision sweep in main.handle_collisions."""

import json

import pygame
import pytest

from asteroid import Asteroid
from main import handle_collisions
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


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_player_collision_ends_game_with_no_shots_in_flight(tmp_path):
    """B1: the player check must run even when the shots group is empty.

    Before the fix the check sat inside `for shot in shots:`, so an asteroid
    overlapping the ship went undetected until the player fired a first shot.
    """
    pygame.init()
    _, _, asteroids, shots = make_groups()

    player = Player(640, 360)
    Asteroid(640, 360, 40)  # distance 0 <= 40 + PLAYER_RADIUS: overlapping
    assert len(shots) == 0

    with pytest.raises(SystemExit):
        handle_collisions(asteroids, shots, player)

    assert any(event["type"] == "player_hit" for event in read_events(tmp_path))
