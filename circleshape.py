import pygame

from constants import COLLISION_RESTITUTION, SCREEN_HEIGHT, SCREEN_WIDTH

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

    @property
    def inverse_mass(self):
        """Resistance to an impulse: 1 / mass. The base body weighs one
        unit; the rock field and the boss override with their own model
        (physics overhaul)."""
        return 1.0

    def effective_velocity(self):
        """The velocity that carries momentum into contact math. The base
        body moves at face value; the rock field overrides so a
        chrono-slowed rock hits with its dilated speed, not its base one
        (physics overhaul)."""
        return self.velocity


def resolve_contact(a, b, e=COLLISION_RESTITUTION):
    """Pure impulse resolution along the center-to-center normal (physics
    overhaul): the one math every contact pass shares.

    Approaching bodies exchange an impulse proportional to their closing
    speed — restitution e scales the bounce, so momentum is conserved
    exactly along the normal while a (1 - e^2) share of the pair's
    kinetic energy dissipates. Both bodies are then pushed apart along
    the normal by the full overlap, split by inverse mass: a light body
    gives way, an immovable one (inverse mass 0) doesn't move at all.
    A separating contact only de-penetrates — no impulse can add speed
    to bodies already flying apart.

    Pure by contract: velocities and positions in, velocities and
    positions out — never kill(), never mint, never an event, never the
    despawned flag. Returns the applied impulse (0.0 for a
    de-penetration-only contact), or None when the bodies aren't
    touching, or when both are immovable and nothing can respond.
    """
    normal = b.position - a.position
    dist = normal.length()
    overlap = a.radius + b.radius - dist
    if overlap <= 0:
        return None  # not touching — nothing to resolve
    normal = normal / dist if dist > 0 else pygame.Vector2(1, 0)
    a_inv, b_inv = a.inverse_mass, b.inverse_mass
    total_inv = a_inv + b_inv
    if total_inv <= 0:
        return None  # two immovable bodies: nothing can respond
    impulse = 0.0
    closing = (b.effective_velocity() - a.effective_velocity()).dot(normal)
    if closing < 0:  # approaching; separating contacts just de-penetrate
        impulse = -(1 + e) * closing / total_inv
        a.velocity -= impulse * a_inv * normal
        b.velocity += impulse * b_inv * normal
    a.position -= normal * overlap * (a_inv / total_inv)
    b.position += normal * overlap * (b_inv / total_inv)
    return impulse