import random

import pygame
from asteroid import Asteroid
from constants import (
    ASTEROID_KINDS,
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    ASTEROID_SPAWN_RATE_SECONDS,
    ASTEROID_SPEED_MAX,
    ASTEROID_SPEED_MIN,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    WAVE_SPAWN_DECAY,
    WAVE_SPAWN_INTERVAL_FLOOR,
    WAVE_SPEED_MAX_STEP,
    WAVE_SPEED_MIN_STEP,
)


def wave_params(wave):
    """Difficulty for a wave, pure so tests pin the math directly (F3).

    The spawn cadence tightens x0.9 per wave down to its floor; the asteroid
    speed band climbs from its wave-1 base. Kept as a plain dict — the
    spec's key interface for this feature.
    """
    return {
        "spawn_interval": max(
            WAVE_SPAWN_INTERVAL_FLOOR,
            ASTEROID_SPAWN_RATE_SECONDS * WAVE_SPAWN_DECAY ** (wave - 1),
        ),
        "speed_min": ASTEROID_SPEED_MIN + WAVE_SPEED_MIN_STEP * (wave - 1),
        "speed_max": ASTEROID_SPEED_MAX + WAVE_SPEED_MAX_STEP * (wave - 1),
    }


class AsteroidField(pygame.sprite.Sprite):
    edges = [
        [
            pygame.Vector2(1, 0),
            lambda y: pygame.Vector2(-ASTEROID_MAX_RADIUS, y * SCREEN_HEIGHT),
        ],
        [
            pygame.Vector2(-1, 0),
            lambda y: pygame.Vector2(
                SCREEN_WIDTH + ASTEROID_MAX_RADIUS, y * SCREEN_HEIGHT
            ),
        ],
        [
            pygame.Vector2(0, 1),
            lambda x: pygame.Vector2(x * SCREEN_WIDTH, -ASTEROID_MAX_RADIUS),
        ],
        [
            pygame.Vector2(0, -1),
            lambda x: pygame.Vector2(
                x * SCREEN_WIDTH, SCREEN_HEIGHT + ASTEROID_MAX_RADIUS
            ),
        ],
    ]

    def __init__(self, game):
        pygame.sprite.Sprite.__init__(self, self.containers)
        # The wave lives on the Game (F2); the field reads it every update.
        self.game = game
        self.spawn_timer = 0.0
        # Asteroids spawned in the current wave. main()'s advance guard needs
        # this: an empty field counts as "cleared" only if the current wave
        # actually had asteroids — at game start and after R-restart the
        # field is empty too, and must not tick the wave counter.
        self.spawned_this_wave = 0

    def start_wave(self):
        """Reset the per-wave clock and the populated guard for a new wave."""
        self.spawn_timer = 0.0
        self.spawned_this_wave = 0

    def spawn(self, radius, position, velocity):
        asteroid = Asteroid(position.x, position.y, radius)
        asteroid.velocity = velocity
        self.spawned_this_wave += 1
        return asteroid

    def update(self, dt):
        # Cadence and speed band come from the wave the game is on (F3).
        params = wave_params(self.game.wave)
        self.spawn_timer += dt
        if self.spawn_timer > params["spawn_interval"]:
            self.spawn_timer = 0

            # spawn a new asteroid at a random edge
            edge = random.choice(self.edges)
            speed = random.randint(params["speed_min"], params["speed_max"])
            velocity = edge[0] * speed
            velocity = velocity.rotate(random.randint(-30, 30))
            position = edge[1](random.uniform(0, 1))
            kind = random.randint(1, ASTEROID_KINDS)
            self.spawn(ASTEROID_MIN_RADIUS * kind, position, velocity)
