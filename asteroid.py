import pygame
import random
from logger import log_event

from circleshape import CircleShape
from constants import ASTEROID_MAX_RADIUS, ASTEROID_MIN_RADIUS, LINE_WIDTH

class Asteroid(CircleShape):
    def __init__(self, x, y, radius):
        super().__init__(x, y, radius)
        self.radius = radius

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
