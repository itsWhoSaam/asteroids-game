"""Black-hole events (insanity threats): a timed gravity well that bends
every trajectory without ever killing anything directly.

The module owns two things: the pure pull math (`accel_at`) and the well
itself. Live holes are also published through a module-level registry that
the main loop refreshes from the sprite group every frame — the same
class-level steering-ref precedent the chrono scale set on Asteroid — so
asteroids, shots, the saucer, and the player can consult gravity where
their velocity already changes, with no import cycles and no per-body
wiring. Pickups and particles never consult it: the well bends bodies,
not debris.
"""

import random

import pygame

from circleshape import CircleShape
from constants import (
    BLACK_HOLE_FIRST_DELAY_S,
    BLACK_HOLE_FIRST_WAVE,
    BLACK_HOLE_JITTER_S,
    BLACK_HOLE_LIFETIME_S,
    BLACK_HOLE_MAX_ACCEL,
    BLACK_HOLE_MIN_DIST,
    BLACK_HOLE_PLAYER_FACTOR,
    BLACK_HOLE_RADIUS,
    BLACK_HOLE_REPEAT_DELAY_S,
    BLACK_HOLE_STRENGTH,
    BLACK_HOLE_FALLOFF,
    BLACK_HOLE_SPAWN_MARGIN,
    BLACK_HOLE_WARNING_S,
    LINE_WIDTH,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from logger import log_event
import sound

# Live wells this frame, written by main() from the sprite group (the
# speed_scale precedent). pull_at reads it; tests may set it directly.
live_holes = []


def accel_at(pos, hole_pos, strength=BLACK_HOLE_STRENGTH,
             falloff=BLACK_HOLE_FALLOFF, cap=BLACK_HOLE_MAX_ACCEL,
             min_dist=BLACK_HOLE_MIN_DIST):
    """Pure acceleration vector toward the hole for a body at `pos`.

    Inverse falloff (`strength / dist ** falloff`) capped at `cap`, with
    `min_dist` keeping the math finite at the core — a body sitting inside
    the well is pulled at the min-dist strength, not flung by a singularity.
    """
    delta = hole_pos - pos
    dist = max(delta.length(), min_dist)
    magnitude = min(strength / dist**falloff, cap)
    if delta.length() == 0:
        # Degenerate center-in-hole case: any direction; the cap holds it.
        return pygame.Vector2(0, magnitude)
    return delta.normalize() * magnitude


def pull_at(position, player=False):
    """The summed pull of every live hole at `position`.

    The ship fights gravity at half strength (BLACK_HOLE_PLAYER_FACTOR) —
    the pull is danger, not a death sentence.
    """
    accel = pygame.Vector2(0, 0)
    for hole in live_holes:
        accel += accel_at(position, hole.position)
    if player:
        accel *= BLACK_HOLE_PLAYER_FACTOR
    return accel


def refresh_live_holes(group):
    """Rebuild the registry from the sprite group — main() calls this once
    per frame, before the world update (the speed_scale precedent: one
    class-level write per frame, no per-body wiring).

    Mutates in place so references imported earlier (tests, evidence
    scripts) stay valid, and group membership is the liveness criterion:
    a well that despawned — or died in a restart clear — drops out the
    same frame, so the pull can never outlive its hole."""
    live_holes[:] = list(group)


class BlackHole(CircleShape):
    """A drifting gravity well on its own lifetime clock.

    It spawns on main's scheduler, pulls every body that asks, and despawns
    when its clock empties — despawned marks it for the same "was not a
    kill" reasoning the asteroids use. It has no kill path of its own: a
    well can be removed early only by the full-restart clear.
    """

    containers = ()

    def __init__(self, x, y):
        super().__init__(x, y, BLACK_HOLE_RADIUS)
        self.lifetime = BLACK_HOLE_LIFETIME_S
        self.despawned = False
        log_event("blackhole_spawned", x=round(x), y=round(y))
        sound.play(sound.SFX_BLACKHOLE)

    @property
    def warning(self):
        """True inside the final blink window — the visual countdown."""
        return 0 < self.lifetime <= BLACK_HOLE_WARNING_S

    def update(self, dt):
        self.lifetime -= dt
        if self.lifetime <= 0:
            self.despawned = True
            self.kill()
            log_event("blackhole_despawned")

    def draw(self, screen):
        # A well reads as a ringed void: outer ring, inner ring, and a dark
        # core. The warning blink doubles the outer ring's visibility on
        # alternating half-cycles — the same blink idiom as the ship's
        # i-frames, and headless-safe (no alpha blit).
        blink_on = not self.warning or (self.lifetime * 6) % 1 < 0.5
        pygame.draw.circle(screen, PALETTE["fringe_r"], self.position,
                           self.radius, LINE_WIDTH)
        pygame.draw.circle(screen, PALETTE["fringe_c"], self.position,
                           self.radius // 2, LINE_WIDTH)
        if blink_on:
            pygame.draw.circle(screen, PALETTE["hud_ink"], self.position,
                               self.radius + 4, 1)


class BlackHoleScheduler:
    """The spawn clock (insanity threats): one well every repeat interval
    (± jitter) from BLACK_HOLE_FIRST_WAVE, never during a boss wave.

    The clock holds — it does not tick — during the gates, so a well is
    never owed from a wave it was barred from.
    """

    def __init__(self):
        self.timer = BLACK_HOLE_FIRST_DELAY_S

    def reset(self):
        """Full-restart hook: the first delay re-arms from scratch."""
        self.timer = BLACK_HOLE_FIRST_DELAY_S

    def update(self, dt, wave, boss_wave):
        """Tick the clock; True when a well should spawn this frame."""
        if wave < BLACK_HOLE_FIRST_WAVE or boss_wave:
            return False
        self.timer -= dt
        if self.timer > 0:
            return False
        self.timer = BLACK_HOLE_REPEAT_DELAY_S + random.uniform(
            -BLACK_HOLE_JITTER_S, BLACK_HOLE_JITTER_S
        )
        return True


def spawn_position():
    """A random well position, kept clear of every screen edge."""
    return (
        random.uniform(BLACK_HOLE_SPAWN_MARGIN, SCREEN_WIDTH - BLACK_HOLE_SPAWN_MARGIN),
        random.uniform(BLACK_HOLE_SPAWN_MARGIN, SCREEN_HEIGHT - BLACK_HOLE_SPAWN_MARGIN),
    )
