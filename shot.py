import pygame
import blackhole
from circleshape import CircleShape
from comicfx import chromatic_circle
from constants import (
    ASTEROID_MAX_RADIUS,
    HOMING_TURN_RATE_S,
    LINE_WIDTH,
    PALETTE,
    SHOT_RADIUS,
)


def homing_steer(position, velocity, target_positions,
                 turn_rate=HOMING_TURN_RATE_S, dt=0.0):
    """Pure: a homing shot's velocity — rotated toward the nearest target
    by at most turn_rate·dt degrees, speed preserved, so the buff bends
    bullets instead of accelerating them.

    No targets (or a zeroed velocity) → unchanged; a target dead-center
    under the shot → unchanged (the heading already points at it); the
    nearest target wins ties by group order."""
    speed = velocity.length()
    if speed == 0 or not target_positions:
        return velocity
    nearest = min(target_positions, key=position.distance_to)
    desired = nearest - position
    if desired.length() == 0:
        return velocity  # sitting on the target: nothing to steer toward
    step = max(-turn_rate * dt, min(turn_rate * dt,
                                    velocity.normalize().angle_to(desired.normalize())))
    return velocity.normalize().rotate(step) * speed


class Shot(CircleShape):
    # Homing (insanity chaos): while the player's HOMING timer runs, main
    # publishes the live asteroid group here every frame — the speed_scale
    # precedent: one class-level write per frame, no per-shot wiring, no
    # import cycle. None keeps every shot flying straight.
    homing_targets = None

    def __init__(self, x, y):
        super().__init__(x, y, SHOT_RADIUS)
        # Run stats (run-stats PR): turret shots tag themselves at the fire
        # site (drones.py) so the sweep's hit counter reads the player's
        # accuracy, not the drones' — the bullets fly the same pipeline.
        self.from_drone = False

    def draw(self, screen):
        # Inked comic tracer (V2): same stack, scaled to the tiny radius.
        chromatic_circle(screen, PALETTE["shot"], self.position, self.radius, LINE_WIDTH)

    def update(self, dt):
        # Insanity threats: live black holes bend every shot's flight —
        # the pull rides the velocity before the position step.
        self.velocity += blackhole.pull_at(self.position) * dt
        # Insanity chaos: while HOMING is armed, every friendly shot (the
        # player's and the drones') steers toward the nearest rock.
        if Shot.homing_targets is not None:
            self.velocity = homing_steer(
                self.position, self.velocity,
                [rock.position for rock in Shot.homing_targets],
                HOMING_TURN_RATE_S, dt,
            )
        self.position += self.velocity * dt
        if self.is_off_screen(ASTEROID_MAX_RADIUS):
            self.kill()
