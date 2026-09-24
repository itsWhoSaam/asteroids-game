"""Timed pickups (engagement F4): a destroyed non-small rock occasionally
pays a drop that changes how you play for a few seconds.

The effect data lives in constants.py — drop chance, per-type durations,
magnitudes — so the idle-economy follow-up can retune or extend effects
without touching gameplay code. This module is just the drifting pickup,
its type enum, and the pure drop decision the sweep consumes.
"""

import enum
import random

import pygame

from circleshape import CircleShape
from constants import (
    ASTEROID_MIN_RADIUS,
    LINE_WIDTH,
    POWERUP_DROP_CHANCE,
    POWERUP_DRIFT_SPEED,
    POWERUP_FONT_SIZE,
    POWERUP_RADIUS,
)


class PowerUpType(enum.StrEnum):
    """The three pickups. Values key the constants tables (F4)."""

    SHIELD = "shield"
    RAPID = "rapid"
    TRIPLE = "triple"


# Uniform selection pool; this order fixes the pick_type roll mapping.
POWERUP_TYPES = (PowerUpType.SHIELD, PowerUpType.RAPID, PowerUpType.TRIPLE)


def drops_powerup(radius, roll):
    """Pure drop decision: a destroyed non-small rock drops a pickup
    POWERUP_DROP_CHANCE of the time.

    Strict `<` puts the boundary roll itself on the no-drop side — a 0.14
    roll drops, the 0.15 chance and up does not — and small rocks never
    drop whatever the roll.
    """
    return radius > ASTEROID_MIN_RADIUS and roll < POWERUP_DROP_CHANCE


def pick_type(roll):
    """Pure uniform type selection: a [0, 1) roll maps evenly across
    POWERUP_TYPES. Clamped so even a sloppy 1.0 roll picks a real type."""
    index = min(int(roll * len(POWERUP_TYPES)), len(POWERUP_TYPES) - 1)
    return POWERUP_TYPES[index]


_label_font_cache = None


def label_font():
    """Lazily built pickup-letter font; pygame.font is ready once pygame.init() ran."""
    global _label_font_cache
    if _label_font_cache is None:
        _label_font_cache = pygame.font.Font(None, POWERUP_FONT_SIZE)
    return _label_font_cache


class PowerUp(CircleShape):
    """A drifting pickup. Constructing one joins its containers like every
    other sprite; the collision sweep reports the collection to the player."""

    def __init__(self, x, y, kind):
        super().__init__(x, y, POWERUP_RADIUS)
        self.kind = kind
        # Slow drift in a random direction: the drop lingers near the rock's
        # death site instead of hanging motionless inside it.
        self.velocity = (
            pygame.Vector2(0, 1).rotate(random.uniform(0, 360)) * POWERUP_DRIFT_SPEED
        )

    def draw(self, screen):
        # White outline like every other entity, with the type's initial
        # stamped in the middle so the pickup reads at a glance.
        pygame.draw.circle(screen, "white", self.position, self.radius, LINE_WIDTH)
        letter = label_font().render(self.kind.value[0].upper(), True, "white")
        screen.blit(letter, letter.get_rect(center=self.position))

    def update(self, dt):
        self.position += self.velocity * dt
        if self.is_off_screen(POWERUP_RADIUS):
            self.kill()
