"""Regression tests for off-screen culling (B2): shots and asteroids must
die once fully outside the screen bounds plus the spawn margin."""

import pygame

from asteroid import Asteroid
from constants import SCREEN_HEIGHT, SCREEN_WIDTH
from shot import Shot


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)

    return updatable, drawable, asteroids, shots


def test_shot_beyond_the_margin_is_culled_from_all_groups():
    pygame.init()
    updatable, drawable, asteroids, shots = make_groups()

    shot = Shot(-200, 360)  # fully beyond the left bound + margin

    shot.update(0.016)

    assert not shot.alive()
    assert len(shots) == 0
    assert len(updatable) == 0
    assert len(drawable) == 0


def test_asteroid_beyond_the_margin_is_culled_from_all_groups():
    pygame.init()
    updatable, drawable, asteroids, shots = make_groups()

    asteroid = Asteroid(SCREEN_WIDTH + 200, SCREEN_HEIGHT + 200, 40)

    asteroid.update(0.016)

    assert not asteroid.alive()
    assert len(asteroids) == 0
    assert len(updatable) == 0
    assert len(drawable) == 0


def test_entity_inside_the_margin_survives_the_update():
    """The AsteroidField spawns at exactly SCREEN + ASTEROID_MAX_RADIUS and
    aims inward; the margin must keep such entities alive."""
    pygame.init()
    updatable, drawable, asteroids, shots = make_groups()

    shot = Shot(SCREEN_WIDTH + 59, 360)  # one px inside the cull edge
    asteroid = Asteroid(SCREEN_WIDTH + 60, 360, 40)  # exactly on the spawn ring

    shot.update(0.016)
    asteroid.update(0.016)

    assert shot.alive()
    assert asteroid.alive()
    assert len(shots) == 1
    assert len(asteroids) == 1
