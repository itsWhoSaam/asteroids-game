import pygame
import random
from logger import log_event

from circleshape import CircleShape
from comicfx import chromatic_circle
from constants import (
    ASTEROID_KINDS,
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    CHIP_HEALTH_PER_TIER,
    LINE_WIDTH,
    PALETTE,
)

# Size-tier order for the palette lookup: tier 1 (small) → 3 (large).
ASTEROID_COLOR_KEYS = ("asteroid_s", "asteroid_m", "asteroid_l")


def asteroid_color(radius):
    """Pure palette hue for a rock, by size tier.

    Tiers mirror chip_threshold's round(radius / ASTEROID_MIN_RADIUS) and
    clamp to the ASTEROID_KINDS band, so any radius resolves to a real
    swatch — small pink up through large violet.
    """
    tier = min(ASTEROID_KINDS, max(1, round(radius / ASTEROID_MIN_RADIUS)))
    return PALETTE[ASTEROID_COLOR_KEYS[tier - 1]]


class Asteroid(CircleShape):
    # Time dilation (chrono powerup): the main loop writes the active
    # scale here every frame — class-level, so spawned and split rocks
    # dilate with the field, and expiry restores base speed by the same
    # write (no per-instance undo state to forget).
    speed_scale = 1.0

    def __init__(self, x, y, radius):
        super().__init__(x, y, radius)
        self.radius = radius
        # Click-chip state (idle core): accumulated click damage, plus the
        # despawn marker the main-loop destruction diff reads to tell a
        # cull (drifted off-screen) from a paid destruction.
        self.chip_damage = 0.0
        self.despawned = False

    @property
    def chip_threshold(self):
        """Chip damage this rock absorbs before dying, by size tier."""
        tier = max(1, round(self.radius / ASTEROID_MIN_RADIUS))
        return tier * CHIP_HEALTH_PER_TIER

    def take_chip(self, amount):
        """Apply one click's chip damage; die through the normal split() path.

        Returns True when this call destroyed the asteroid. Shots never
        route here — they keep calling split() directly, so their
        instant-kill semantics (pinned by the sibling tests) hold untouched.
        """
        if not self.alive():
            return False
        self.chip_damage += amount
        if self.chip_damage >= self.chip_threshold:
            self.split()
            return True
        return False

    def draw(self, screen):
        # Inked comic rock (V2): the tier hue stays the fill stroke; the
        # chromatic stack adds black ink and the red/cyan fringes around it.
        chromatic_circle(
            screen,
            asteroid_color(self.radius),
            self.position,
            self.radius,
            LINE_WIDTH
        )
    def update(self, dt):
        # Chrono time dilation rides the frame step: the active scale
        # (1.0 baseline) is the class attribute the main loop publishes.
        self.position += self.velocity * self.speed_scale * dt
        if self.is_off_screen(ASTEROID_MAX_RADIUS):
            # Mark the cull before kill(): a rock that drifted off-screen
            # was never destroyed, so the idle diff poll must not mint for it.
            self.despawned = True
            self.kill()

    def split(self):
        if not self.alive():
            return
        self.kill()
        if self.radius <= ASTEROID_MIN_RADIUS:
            return
        log_event("asteroid_split")
        rand_angle = random.uniform(20, 50)
        first_direction = self.velocity.rotate(rand_angle)
        second_direction = self.velocity.rotate(-rand_angle)
        new_radius = self.radius - ASTEROID_MIN_RADIUS
        a1 = Asteroid(self.position.x, self.position.y, new_radius)
        a2 = Asteroid(self.position.x, self.position.y, new_radius)
        a1.velocity = first_direction * 1.2
        a2.velocity = second_direction * 1.2
