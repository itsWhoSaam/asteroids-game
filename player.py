import pygame
from circleshape import CircleShape
from constants import (
    LINE_WIDTH,
    PLAYER_BLINK_HZ,
    PLAYER_INVULNERABILITY_SECONDS,
    PLAYER_RADIUS,
    PLAYER_SHOOT_SPEED,
    PLAYER_SPEED,
    PLAYER_TURN_SPEED,
    PLAYER_SHOOT_COOLDOWN_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from shot import Shot


class Player(CircleShape):
    def __init__(self, x, y):
        super().__init__(x, y, PLAYER_RADIUS )
        self.shot_cooldown_timer = 0
        # Grace window after a respawn: dt-decremented like shot_cooldown_timer.
        self.invulnerability_timer = 0.0
        self.rotation = 0

    @property
    def invulnerable(self):
        return self.invulnerability_timer > 0

    def respawn(self):
        """Center the ship, zero its velocity, grant the grace window.

        Invulnerability is what lets a respawning ship sit safely inside an
        asteroid it materialized on — the collision sweep checks it before
        resolving any hit.
        """
        self.position = pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
        self.velocity = pygame.Vector2(0, 0)
        self.invulnerability_timer = PLAYER_INVULNERABILITY_SECONDS

    # in the Player class
    def triangle(self):
        forward = pygame.Vector2(0, 1).rotate(self.rotation)
        right = pygame.Vector2(0, 1).rotate(self.rotation + 90) * self.radius / 1.5
        a = self.position + forward * self.radius
        b = self.position - forward * self.radius - right
        c = self.position - forward * self.radius + right
        return [a, b, c]
    
    def draw(self, screen):
        # Grace-window blink: skip the draw on alternate half-cycles so the
        # invulnerable ship flickers instead of sitting inside a rock unseen.
        if self.invulnerable and (self.invulnerability_timer * PLAYER_BLINK_HZ) % 1 >= 0.5:
            return
        pygame.draw.polygon(
            screen,
            "white",
            self.triangle(),
            LINE_WIDTH
        )

    def rotate(self, dt):
        self.rotation += PLAYER_TURN_SPEED * dt

    def update(self, dt):
        keys = pygame.key.get_pressed()
        self.shot_cooldown_timer -= dt
        self.invulnerability_timer -= dt

        if keys[pygame.K_a]:
            self.rotate(-dt)
        if keys[pygame.K_d]:
            self.rotate(dt)
        if keys[pygame.K_w]:
            self.move(dt)
        if keys[pygame.K_s]:
            self.move(-dt)
        if keys[pygame.K_SPACE]:
            self.shoot()

    def shoot(self):
        if self.shot_cooldown_timer > 0:
            return
        self.shot_cooldown_timer = PLAYER_SHOOT_COOLDOWN_SECONDS
        shot = Shot(self.position.x, self.position.y)
        shot.velocity = pygame.Vector2(0,1).rotate(self.rotation) * PLAYER_SHOOT_SPEED

    def move (self, dt):
        unit_vector = pygame.Vector2(0, 1)
        rotated_vector = unit_vector.rotate(self.rotation)
        rotated_with_speed_vector = rotated_vector * PLAYER_SPEED * dt
        self.position += rotated_with_speed_vector