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
from comicfx import cached_text, chromatic_circle
from constants import (
    ASTEROID_MIN_RADIUS,
    LINE_WIDTH,
    PALETTE,
    POWERUP_DROP_CHANCE,
    POWERUP_DRIFT_SPEED,
    POWERUP_FONT_SIZE,
    POWERUP_MAGNET_ACCELERATION,
    POWERUP_MAGNET_MAX_SPEED,
    POWERUP_MAGNET_RADIUS,
    POWERUP_RADIUS,
)


class PowerUpType(enum.StrEnum):
    """The four pickups. Values key the constants tables (F4)."""

    SHIELD = "shield"
    RAPID = "rapid"
    TRIPLE = "triple"
    MAGNET = "magnet"


# Uniform selection pool; this order fixes the pick_type roll mapping.
# MAGNET appends at the end so every existing type keeps its roll band.
POWERUP_TYPES = (
    PowerUpType.SHIELD,
    PowerUpType.RAPID,
    PowerUpType.TRIPLE,
    PowerUpType.MAGNET,
)

# Per-kind palette keys (visual V1): each pickup keeps its effect identity
# color — SHIELD cyan, RAPID orange, TRIPLE magenta, MAGNET green.
POWERUP_COLOR_KEYS = {
    PowerUpType.SHIELD: "powerup_shield",
    PowerUpType.RAPID: "powerup_rapid",
    PowerUpType.TRIPLE: "powerup_triple",
    PowerUpType.MAGNET: "powerup_magnet",
}


def powerup_color(kind):
    """Pure palette hue for a pickup, by its effect type."""
    return PALETTE[POWERUP_COLOR_KEYS[kind]]


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


def magnet_pull(position, attractor, velocity, radius=POWERUP_MAGNET_RADIUS,
                strength=POWERUP_MAGNET_ACCELERATION,
                max_speed=POWERUP_MAGNET_MAX_SPEED, dt=1 / 60):
    """Pure magnet step (Tier 3): the velocity a body under the pull has
    after this frame.

    Accelerates toward the attractor, eased linearly from full strength at
    its center to zero at the rim — a body just inside the band barely
    feels the field, one closing in pulls hard. The cap bounds the total
    speed so the grab can never sling a body past the ship. A body at or
    beyond the radius (the boundary rides the no-pull side, like the drop
    roll's strict `<`), or exactly on the attractor where direction is
    undefined, keeps its velocity untouched. Force, not teleport: the
    position is never read for mutation — the caller integrates the
    returned velocity with its own update.

    All arguments are pygame.Vector2-compatible; the return is a Vector2.
    """
    offset = attractor - position
    distance = offset.length()
    if distance >= radius or distance <= 0:
        return pygame.Vector2(velocity)
    falloff = 1.0 - distance / radius
    pulled = velocity + offset.normalize() * (strength * falloff * dt)
    if pulled.length() > max_speed:
        pulled = pulled * (max_speed / pulled.length())
    return pulled


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
        # The kind's identity color rings the pickup and stamps its initial,
        # so the type reads at a glance across the field. Inked pickup (V2):
        # the ring goes through the chromatic stack like every other entity.
        color = powerup_color(self.kind)
        chromatic_circle(screen, color, self.position, self.radius, LINE_WIDTH)
        # V4: the letter comes from the shared (word, color, size) cache —
        # one render per kind for the process, not one per frame per pickup
        # (the survey's flagged allocation pattern, killed here).
        letter = cached_text(self.kind.value[0].upper(), color, POWERUP_FONT_SIZE)
        screen.blit(letter, letter.get_rect(center=self.position))

    def update(self, dt):
        self.position += self.velocity * dt
        if self.is_off_screen(POWERUP_RADIUS):
            self.kill()
