import pygame
from circleshape import CircleShape
from comicfx import chromatic_circle
from constants import ASTEROID_MAX_RADIUS, LINE_WIDTH, PALETTE, SHOT_RADIUS


class Shot(CircleShape):
    def __init__(self, x, y):
        super().__init__(x, y, SHOT_RADIUS)
        # Run stats (run-stats PR): turret shots tag themselves at the fire
        # site (drones.py) so the sweep's hit counter reads the player's
        # accuracy, not the drones' — the bullets fly the same pipeline.
        self.from_drone = False
        # UFO saucer (Tier 3): the saucer's aimed shots tag themselves too —
        # the sweep lets only these reach the ship, and the accuracy read
        # stays the player's alone.
        self.from_ufo = False

    def draw(self, screen):
        # Inked comic tracer (V2): same stack, scaled to the tiny radius.
        chromatic_circle(screen, PALETTE["shot"], self.position, self.radius, LINE_WIDTH)

    def update(self, dt):
        self.position += self.velocity * dt
        if self.is_off_screen(ASTEROID_MAX_RADIUS):
            self.kill()
