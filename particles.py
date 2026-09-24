"""Explosion particles and screen shake (engagement F5): destruction looks
and feels like destruction.

Two effects, one module. Debris bursts are size-scaled — a bigger rock dies
into a bigger cloud — and each spark dies exactly at its lifetime, fading by
size (no per-pixel alpha, so the draw is headless-safe). The shake decays
exponentially and ever only offsets the draw origin: entity positions and
collision inputs are never touched by it.
"""

import random

import pygame

from circleshape import CircleShape
from constants import (
    PALETTE,
    PARTICLES_PER_RADIUS,
    PARTICLE_LIFETIME_SECONDS,
    PARTICLE_MAX_SPEED,
    PARTICLE_MIN_SPEED,
    PARTICLE_RADIUS,
    SHAKE_DECAY,
    SHAKE_MAX_MAGNITUDE,
    SHAKE_STOP_EPSILON,
)


def burst_count(base_radius, intensity=1.0):
    """Pure burst sizing: the particle count scales with the destroyed
    body's radius (and the intensity multiplier), so a larger rock dies
    into a visibly larger cloud."""
    return max(1, int(base_radius * intensity * PARTICLES_PER_RADIUS))


def burst(position, base_radius, intensity=1.0):
    """Spawn one debris burst at `position`. Particles join their containers
    like every other sprite, so the call site needs no group argument."""
    for _ in range(burst_count(base_radius, intensity)):
        direction = pygame.Vector2(0, 1).rotate(random.uniform(0, 360))
        speed = random.uniform(PARTICLE_MIN_SPEED, PARTICLE_MAX_SPEED) * intensity
        Particle(position.x, position.y, direction * speed)


class Particle(CircleShape):
    """One debris spark: drifts outward, ages, dies at its lifetime.

    The remaining-life fraction drives the fade — the spark shrinks to
    nothing as its clock runs out. Size-only fade (no alpha blit) keeps the
    render safe under the SDL dummy drivers.
    """

    def __init__(self, x, y, velocity):
        super().__init__(x, y, PARTICLE_RADIUS)
        self.velocity = velocity
        self.lifetime = PARTICLE_LIFETIME_SECONDS
        self.age = 0.0

    @property
    def life_fraction(self):
        """1.0 at birth → 0.0 at (or past) the lifetime."""
        return max(0.0, 1.0 - self.age / self.lifetime)

    def update(self, dt):
        self.position += self.velocity * dt
        self.age += dt
        if self.age >= self.lifetime:
            self.kill()

    def draw(self, screen):
        # Filled and shrinking: radius scales with the remaining life,
        # floored at 1px so the final moments still render.
        radius = max(1, int(round(PARTICLE_RADIUS * self.life_fraction)))
        pygame.draw.circle(screen, PALETTE["spark"], self.position, radius)


class Shake:
    """Screen shake as a decaying magnitude, applied at the draw origin.

    `kick` adds trauma (capped), `update` decays it exponentially with the
    clamped dt, and `offset` is the only output — a pixel shift the render
    loop applies when blitting the world. Entities never see this object.
    """

    def __init__(self):
        self.magnitude = 0.0

    def kick(self, magnitude):
        """Add trauma; a cap keeps stacked kicks from flinging the world."""
        self.magnitude = min(self.magnitude + magnitude, SHAKE_MAX_MAGNITUDE)

    def update(self, dt):
        # Exponential decay with the clamped dt: magnitude *= decay ** dt.
        # Below the stop threshold it snaps to exactly zero — the decay
        # alone would only approach zero forever.
        self.magnitude *= SHAKE_DECAY**dt
        if self.magnitude < SHAKE_STOP_EPSILON:
            self.magnitude = 0.0

    def offset(self):
        """The draw-origin shift for this frame: a fresh random direction at
        the current magnitude, rounded for the blit. (0, 0) once still — the
        calm frame is pixel-identical to a no-shake render."""
        if self.magnitude <= 0:
            return (0, 0)
        direction = pygame.Vector2(0, 1).rotate(random.uniform(0, 360))
        x, y = direction * self.magnitude
        # Floats, not rounded ints: rounding would inflate the length past
        # the magnitude, and the blit truncates toward zero (never past it).
        return (x, y)
