import pygame
import random
from logger import log_event

from circleshape import CircleShape
from constants import (
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    CHIP_HEALTH_PER_TIER,
    LINE_WIDTH,
)

class Asteroid(CircleShape):
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
        pygame.draw.circle(
            screen,
            "white",
            self.position,
            self.radius,
            LINE_WIDTH
        )
    def update(self, dt):
        self.position += self.velocity * dt
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
