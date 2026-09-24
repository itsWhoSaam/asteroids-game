import pygame

from constants import SCREEN_HEIGHT, SCREEN_WIDTH

# Base class for game objects
class CircleShape(pygame.sprite.Sprite):
    def __init__(self, x, y, radius):
        # we will be using this later
        if hasattr(self, "containers"):
            super().__init__(self.containers)
        else:
            super().__init__()

        self.position = pygame.Vector2(x, y)
        self.velocity = pygame.Vector2(0, 0)
        self.radius = radius

    def draw(self, screen):
        # must override
        pass

    def update(self, dt):
        # must override
        pass

    def is_off_screen(self, margin):
        """True once fully outside the screen bounds by `margin` on any side."""
        x, y = self.position
        return (
            x < -margin
            or x > SCREEN_WIDTH + margin
            or y < -margin
            or y > SCREEN_HEIGHT + margin
        )

    def collides_with(self, other):
        return self.position.distance_to(other.position) <= self.radius + other.radius