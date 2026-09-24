"""Structural smoke test for the extracted collision sweep.

Behavioral regression tests (game over on player collision, no same-frame
double splits) belong to the collision-fix PR: they must fail against this
sweep as it is today. This file only pins that handle_collisions is
extracted and runnable standalone, headless.
"""

import pygame

from main import handle_collisions
from asteroid import Asteroid
from player import Player


def test_handle_collisions_runs_with_overlapping_asteroid_and_no_shots():
    """The sweep executes cleanly with an empty shots group.

    Pins current behavior: the player check lives inside the shot loop, so
    an asteroid overlapping the player triggers nothing when the player has
    not fired. The collision-fix PR replaces this expectation with the
    game-over regression test.
    """
    pygame.init()

    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)

    player = Player(640, 360)
    Asteroid(640, 360, 40)  # distance 0 <= 40 + PLAYER_RADIUS: overlapping

    handle_collisions(asteroids, shots, player)

    assert player.alive()
