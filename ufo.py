"""The UFO saucer (Tier 3): a timed hostile crossing worth big points.

Every UFO_SPAWN_INTERVAL_S of live play a saucer enters from a random screen
edge and crosses with a sinusoidal drift, firing aimed shots at the player on
its own cadence. Everything reuses an existing seam — no new system sits
beside the game, everything plugs into it:

- The saucer is a CircleShape sprite in the ordinary groups, so the pause
  and menu freeze, the logger's state snapshots, and the render passes see
  it for free.
- Its shots are real Shot instances tagged from_ufo — they ride the shared
  sweep like drone shots: they split rocks (the destruction diff mints
  through the one economy path) and they are the only shots that can reach
  the ship, which they damage through Game.player_hit (shield, burst, shake,
  respawn — the one hit flow, invulnerability honored).
- The saucer dies to a single shot: burst + explosion at the site, its own
  points_for tier added to the score, and a mint off the same frame-diff
  poll the rocks pay — destroyed_ufos below mirrors destroyed_asteroids,
  culls (a crossing that exits) never mint.

All timers are dt-based; every tunable lives in the appended UFO section of
constants.py.
"""

import math
import random

import pygame

from circleshape import CircleShape
from comicfx import chromatic_polygon
from constants import (
    LINE_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHOT_RADIUS,
    UFO_DOME_COLOR,
    UFO_EDGE_MARGIN,
    UFO_FIRE_INTERVAL_S,
    UFO_HULL_COLOR,
    UFO_LIGHT_COLOR,
    UFO_RADIUS,
    UFO_SHOT_SPEED,
    UFO_SPAWN_INTERVAL_S,
    UFO_SPEED,
    UFO_WOBBLE_AMPLITUDE,
    UFO_WOBBLE_HZ,
)
from logger import log_event
from shot import Shot


def ufo_spawn_plan(rng=random):
    """The entry plan for one saucer: (position, velocity, wobble_axis, edge).

    Pure (the random.Random instance is injectable): a random edge sends the
    saucer inward — the AsteroidField's edge tables' shape, minus the heading
    jitter, because the crossing is a straight line the sine wobble rides
    perpendicular to. The position starts exactly at the cull margin, so the
    first inward step enters the screen (is_off_screen is a strict <). The
    along-edge fraction is kept off the corners (0.2–0.8) so a crossing is
    always visible.
    """
    edge = rng.randrange(4)
    along = rng.uniform(0.2, 0.8)
    if edge == 0:  # left edge, heading right
        position = pygame.Vector2(-UFO_EDGE_MARGIN, along * SCREEN_HEIGHT)
        velocity = pygame.Vector2(UFO_SPEED, 0)
    elif edge == 1:  # right edge, heading left
        position = pygame.Vector2(
            SCREEN_WIDTH + UFO_EDGE_MARGIN, along * SCREEN_HEIGHT
        )
        velocity = pygame.Vector2(-UFO_SPEED, 0)
    elif edge == 2:  # top edge, heading down
        position = pygame.Vector2(along * SCREEN_WIDTH, -UFO_EDGE_MARGIN)
        velocity = pygame.Vector2(0, UFO_SPEED)
    else:  # bottom edge, heading up
        position = pygame.Vector2(
            along * SCREEN_WIDTH, SCREEN_HEIGHT + UFO_EDGE_MARGIN
        )
        velocity = pygame.Vector2(0, -UFO_SPEED)
    wobble_axis = velocity.rotate(90).normalize()
    return position, velocity, wobble_axis, edge


def aim_vector(from_pos, to_pos):
    """Unit vector from a firing position toward a target position — pure.

    A zero-length aim (saucer exactly on the target) fires along +x rather
    than dividing by zero.
    """
    direction = pygame.Vector2(to_pos) - pygame.Vector2(from_pos)
    if direction.length() == 0:
        return pygame.Vector2(1, 0)
    return direction.normalize()


def _ellipse_points(rx, ry, steps=28):
    """A closed ellipse polygon around (0, 0), precomputed once — the hull's
    lens shape and the dome's arc both come from here. Deterministic module
    geometry (no RNG), so drawing is headless-safe and repeatable."""
    return [
        pygame.Vector2(
            rx * math.cos(2 * math.pi * i / steps),
            ry * math.sin(2 * math.pi * i / steps),
        )
        for i in range(steps)
    ]


# The saucer silhouette, relative to its center: a wide hull lens under a
# glass dome, with running lights across the hull's mid band.
UFO_HULL_POINTS = [(p.x, p.y) for p in _ellipse_points(UFO_RADIUS, UFO_RADIUS * 0.45)]
UFO_DOME_POINTS = [(p.x, p.y) for p in _ellipse_points(UFO_RADIUS * 0.45, UFO_RADIUS * 0.5, 16)]
UFO_LIGHT_OFFSETS = (-UFO_RADIUS * 0.45, 0.0, UFO_RADIUS * 0.45)
UFO_LIGHT_RADIUS = 3


class UFO(CircleShape):
    """One saucer: crossing, wobbling, firing — dying to a single shot.

    The live player is injected at spawn (the AsteroidField-gets-Game
    precedent) so update() can aim; a None player never fires, which is
    exactly what the purity tests want — they drive fire() directly.
    """

    containers = ()

    def __init__(self, player=None, rng=random):
        plan_position, velocity, wobble_axis, edge = ufo_spawn_plan(rng)
        super().__init__(plan_position.x, plan_position.y, UFO_RADIUS)
        self.velocity = velocity
        # The crossing's straight baseline; the drawn and colliding position
        # swings perpendicular to it around this point.
        self.base_position = pygame.Vector2(plan_position)
        self.wobble_axis = wobble_axis
        self.wobble_phase = 0.0
        self.edge = edge
        # Cull flag (the asteroid's despawned precedent): a crossing that
        # exits the far edge never mints through the frame diff.
        self.despawned = False
        # Fire clock, dt-decremented like every timer in the codebase. The
        # full interval up front: the first aimed shot waits one cadence.
        self.fire_timer = UFO_FIRE_INTERVAL_S
        self.player = player

    def update(self, dt):
        # Sinusoidal drift: the baseline advances along the crossing line,
        # the position swings perpendicular to it. Pure kinematics — the
        # wobble never changes the crossing's progress.
        self.wobble_phase = (self.wobble_phase + UFO_WOBBLE_HZ * 360.0 * dt) % 360.0
        self.base_position += self.velocity * dt
        self.position = self.base_position + self.wobble_axis * (
            UFO_WOBBLE_AMPLITUDE * math.sin(math.radians(self.wobble_phase))
        )
        if self.is_off_screen(UFO_EDGE_MARGIN):
            self.despawned = True
            self.kill()
            return
        if self.player is not None:
            # Aimed-fire cadence: the next shot is a full interval after
            # each one (exact reset, not the turret's overshoot carry — the
            # rhythm cannot depend on where a fractional frame lands the
            # clock, and at this cadence the two are indistinguishable).
            self.fire_timer -= dt
            if self.fire_timer <= 0:
                self.fire_timer = UFO_FIRE_INTERVAL_S
                self.fire(self.player.position)

    def fire(self, target_position):
        """One aimed Shot from the saucer's hull edge into the shared shots
        group (Shot.containers — the drone fire pattern).

        The muzzle sits outside the hull (radius + shot radius + 2 px along
        the aim), so the fresh bullet cannot overlap its own saucer the
        frame it spawns — the sweep would read that as an instant self-kill.
        """
        aim = aim_vector(self.position, target_position)
        muzzle = self.position + aim * (UFO_RADIUS + SHOT_RADIUS + 2)
        shot = Shot(muzzle.x, muzzle.y)
        shot.velocity = aim * UFO_SHOT_SPEED
        shot.from_ufo = True
        return shot

    def draw(self, screen):
        # Inked comic saucer: chromatic strokes on hull and dome (the V2
        # stack on a shape the rocks never use), plain filled running lights
        # across the hull band (the drone-marker precedent — no per-pixel
        # alpha, headless-safe).
        x, y = self.position.x, self.position.y
        hull = [(x + px, y + py) for (px, py) in UFO_HULL_POINTS]
        dome = [(x + px, y - UFO_RADIUS * 0.35 + py) for (px, py) in UFO_DOME_POINTS]
        chromatic_polygon(screen, UFO_HULL_COLOR, hull, LINE_WIDTH)
        chromatic_polygon(screen, UFO_DOME_COLOR, dome, LINE_WIDTH)
        for offset in UFO_LIGHT_OFFSETS:
            pygame.draw.circle(
                screen,
                UFO_LIGHT_COLOR,
                (x + offset, y),
                UFO_LIGHT_RADIUS,
            )


def destroyed_ufos(previous, current):
    """Saucers that were live last frame and are gone now, minus culls.

    The frame-diff mirror of main.destroyed_asteroids, kept here so every
    UFO behavior lives in one module: a shot-down saucer pays its mint
    through the same economy poll; one that crossed and exited is flagged
    despawned and pays nothing.
    """
    return [ufo for ufo in previous if ufo not in current and not ufo.despawned]


class UFOSpawner:
    """The saucer clock: one entry every UFO_SPAWN_INTERVAL_S of live play.

    A plain object updated by main's update_world beside the drone bay —
    not a sprite — because it needs the live player (the saucer's firing
    target) that sprite update(dt) signatures cannot carry. The pause and
    menu freeze come free: update_world returns early before reaching here.
    """

    def __init__(self):
        # The full interval up front: the first saucer waits one cadence.
        self.timer = UFO_SPAWN_INTERVAL_S

    def reset(self):
        """A fresh run starts the saucer clock over — restart_run lands
        here (the second restart hook beside Game.restart clearing the
        saucers themselves)."""
        self.timer = UFO_SPAWN_INTERVAL_S

    def spawn(self, player):
        """One saucer entry, logged per the powerup_spawned precedent."""
        ufo = UFO(player)
        log_event("ufo_spawned", edge=ufo.edge)
        return ufo

    def update(self, dt, player):
        self.timer -= dt
        if self.timer > 0:
            return
        # += keeps any overshoot, so the cadence stays a true interval.
        self.timer += UFO_SPAWN_INTERVAL_S
        self.spawn(player)
