import random

import pygame
from asteroid import Asteroid, Mine, boss_tier, mine_spawn_rolls_in
from constants import (
    ASTEROID_KINDS,
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    ASTEROID_SPAWN_RATE_SECONDS,
    ASTEROID_SPEED_MAX,
    ASTEROID_SPEED_MIN,
    BOSS_WAVE_INTERVAL,
    DIFFICULTY_DEFAULT,
    DIFFICULTY_TABLE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    WAVE_SPAWN_DECAY,
    WAVE_SPAWN_INTERVAL_FLOOR,
    WAVE_SPEED_MAX_STEP,
    WAVE_SPEED_MIN_STEP,
)


def wave_params(wave, mode=DIFFICULTY_DEFAULT):
    """Difficulty for a wave, pure so tests pin the math directly (F3).

    The spawn cadence tightens x0.9 per wave down to its floor; the asteroid
    speed band climbs from its wave-1 base. Kept as a plain dict — the
    spec's key interface for this feature.

    Boss waves (insanity threats): every BOSS_WAVE_INTERVAL-th wave returns
    the boss dict instead — the boss IS the wave's population, so the field
    spawns nothing. The zero cadence/speeds are inert filler keeping the
    dict shape uniform for callers that read all keys.

    Tier 2 difficulty modes: the mode's multipliers scale the interval and
    the whole speed band (optional kwarg — the handle_collisions precedent —
    so the pinned single-argument calls keep their exact Normal numbers).
    Multipliers are positive, so the Easy >= Normal >= Hard orderings survive
    the scaling; the shared floor can equalize the intervals at late waves,
    which the monotonicity tests allow. Speeds round to ints — the field's
    random.randint needs them and Normal's 1.0 keeps the exact legacy band.
    """
    if wave % BOSS_WAVE_INTERVAL == 0:
        return {
            "boss": True,
            "tier": boss_tier(wave),
            "spawn_interval": 0.0,
            "speed_min": 0,
            "speed_max": 0,
        }
    cfg = DIFFICULTY_TABLE[mode]
    return {
        "spawn_interval": max(
            WAVE_SPAWN_INTERVAL_FLOOR,
            ASTEROID_SPAWN_RATE_SECONDS
            * WAVE_SPAWN_DECAY ** (wave - 1)
            * cfg["spawn_interval_mult"],
        ),
        "speed_min": int(
            round((ASTEROID_SPEED_MIN + WAVE_SPEED_MIN_STEP * (wave - 1)) * cfg["speed_mult"])
        ),
        "speed_max": int(
            round((ASTEROID_SPEED_MAX + WAVE_SPEED_MAX_STEP * (wave - 1)) * cfg["speed_mult"])
        ),
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

    def spawn(self, radius, position, velocity, cls=Asteroid):
        """Spawn one rock; the optional class kwarg (the handle_collisions
        precedent) lets the mine roll arm a Mine on the same bookkeeping —
        every existing spawn(radius, position, velocity) call keeps its
        exact meaning."""
        asteroid = cls(position.x, position.y, radius)
        asteroid.velocity = velocity
        self.spawned_this_wave += 1
        return asteroid

    def update(self, dt):
        # Cadence and speed band come from the wave the game is on (F3),
        # scaled by the run's difficulty mode (Tier 2).
        params = wave_params(self.game.wave, self.game.mode)
        if params.get("boss"):
            # Boss wave (insanity threats): the field spawns nothing — the
            # boss is the wave's population, spawned by main's scheduler.
            return
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
            radius = ASTEROID_MIN_RADIUS * kind
            if mine_spawn_rolls_in(random.random()):
                # A rare armed variant (Tier 3): the mine rides the rolled
                # kind's radius and the rolled velocity — the variant
                # changes the death, not the drift.
                self.spawn(radius, position, velocity, Mine)
            else:
                self.spawn(radius, position, velocity)
