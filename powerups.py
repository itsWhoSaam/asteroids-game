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
    MYSTERY_DROP_CHANCE,
    MYSTERY_CURSE_CHANCE,
    PALETTE,
    POWERUP_DROP_CHANCE,
    POWERUP_DRIFT_SPEED,
    POWERUP_FONT_SIZE,
    POWERUP_RADIUS,
)


class PowerUpType(enum.StrEnum):
    """The pickups (insanity chaos grows the pool from three to nine).
    Values key the constants tables (F4); MYSTERY is the wildcard — its
    contents roll only when collected."""

    SHIELD = "shield"
    RAPID = "rapid"
    TRIPLE = "triple"
    PIERCE = "pierce"
    HOMING = "homing"
    BOMB = "bomb"
    REVERSE = "reverse"
    DISARM = "disarm"
    MYSTERY = "mystery"


# The six buffs (insanity chaos): direct drops draw evenly from this pool,
# and a mystery open falls back to it 75% of the time. Order fixes both
# roll mappings (pick_type and mystery_pick_type).
BUFF_TYPES = (
    PowerUpType.SHIELD,
    PowerUpType.RAPID,
    PowerUpType.TRIPLE,
    PowerUpType.PIERCE,
    PowerUpType.HOMING,
    PowerUpType.BOMB,
)

# The two curses: mystery contents only. A curse landing on the field as a
# visible, avoidable letter would be a non-event — hidden inside the ?
# pickup, the reveal is the gamble ("stripped on reveal" only means
# something when the curse had a hiding place).
CURSE_TYPES = (PowerUpType.REVERSE, PowerUpType.DISARM)

# Direct-drop selection pool: the six buffs (grew from the original three —
# the Curses ride the mystery wildcard instead).
POWERUP_TYPES = BUFF_TYPES

# The ? pickup's stamp: the wildcard reads as a question mark, not an M —
# the gamble is the point. Every other kind stamps its initial.
PICKUP_LABELS = {PowerUpType.MYSTERY: "?"}

# Per-kind palette keys (visual V1): each pickup keeps its effect identity
# color — SHIELD cyan, RAPID orange, TRIPLE magenta, and the ? violet.
POWERUP_COLOR_KEYS = {
    PowerUpType.SHIELD: "powerup_shield",
    PowerUpType.RAPID: "powerup_rapid",
    PowerUpType.TRIPLE: "powerup_triple",
    PowerUpType.MYSTERY: "powerup_mystery",
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


def drop_type(roll):
    """Pure: what a paid drop is (insanity chaos). The first 40% of the roll
    is the ? wildcard — its contents roll only on collect — the rest an
    equal draw from the six buffs. Curses never drop directly: the reveal
    is the gamble, and the drop roll's remap mirrors mystery_pick_type's."""
    if roll < MYSTERY_DROP_CHANCE:
        return PowerUpType.MYSTERY
    buff_roll = (roll - MYSTERY_DROP_CHANCE) / (1.0 - MYSTERY_DROP_CHANCE)
    return pick_type(buff_roll)


def mystery_pick_type(roll):
    """Pure decision for a collected ? pickup (insanity chaos): the first
    25% of the roll is the sting — a curse, equal odds reverse/disarm —
    the rest an equal draw from the six buffs. The reveal logs
    curse_revealed and plays SFX_CURSE: the sound that makes the next ?
    hesitate."""
    if roll < MYSTERY_CURSE_CHANCE:
        return CURSE_TYPES[int(roll / MYSTERY_CURSE_CHANCE * len(CURSE_TYPES))]
    buff_roll = (roll - MYSTERY_CURSE_CHANCE) / (1.0 - MYSTERY_CURSE_CHANCE)
    return BUFF_TYPES[int(buff_roll * len(BUFF_TYPES)) % len(BUFF_TYPES)]


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
        # The kind's identity color rings the pickup and stamps its label —
        # its initial, or the wildcard's "?" — so the type reads at a glance
        # across the field.
        color = powerup_color(self.kind)
        pygame.draw.circle(screen, color, self.position, self.radius, LINE_WIDTH)
        label = PICKUP_LABELS.get(self.kind, self.kind.value[0].upper())
        letter = label_font().render(label, True, color)
        screen.blit(letter, letter.get_rect(center=self.position))

    def update(self, dt):
        self.position += self.velocity * dt
        if self.is_off_screen(POWERUP_RADIUS):
            self.kill()
