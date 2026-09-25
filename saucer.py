"""Enemy saucers (insanity threats): from wave 2, hostiles cross the field
and fire back — the first things in the game that shoot at you.

A saucer enters from a random side edge, crosses horizontally, and rides a
sine bob; it fires real shots into a separate enemy group the sweep treats
as hostile. Two kinds from the SAUCER_KINDS table: big saucers cross
slower and fire 3-way spreads, small saucers cross fast and fire aimed
single shots — worth far more points. Killing a saucer pays through
register_kill like every shot kill; drifting off-screen is a cull
(despawned), never a paid kill.

The projectiles stay visually identical to player shots (locked decision):
hostile fire is heard, not seen — until it hits you.
"""

import math
import random

import pygame

from circleshape import CircleShape
from blackhole import pull_at
from constants import (
    LINE_WIDTH,
    PALETTE,
    SAUCER_BOB_AMPLITUDE,
    SAUCER_BOB_FREQUENCY,
    SAUCER_EDGE_MARGIN,
    SAUCER_FIRST_WAVE,
    SAUCER_KINDS,
    SAUCER_KIND_ORDER,
    SAUCER_RADIUS,
    SAUCER_SPAWN_INTERVAL_S,
    SAUCER_SPAWN_JITTER_S,
    SAUCER_SPREAD_DEGREES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHOP_PANEL_HEIGHT,
)
from logger import log_event
from shot import Shot
import sound


def saucer_fire_params(kind):
    """Pure: the kind's fire/points table — the spec's key interface."""
    return SAUCER_KINDS[kind]


def next_saucer_kind(index):
    """Pure alternation: spawns cycle the kind order forever."""
    return SAUCER_KIND_ORDER[index % len(SAUCER_KIND_ORDER)]


class SaucerShot(Shot):
    """Hostile fire. Identical flight (move, cull, gravity) as the player
    shot — the group it joins is what makes it hostile."""


class Saucer(CircleShape):
    """A hostile saucer: horizontal cross + sine bob, firing at the ship.

    The bob rides on a drifting base position: gravity (the live-hole
    registry) and the cross velocity move the base, and the bob overlays it,
    so the drawn-and-collided position always includes both. main() updates
    saucers explicitly with the player and the enemy group — they are not in
    the updatable group, whose group-update passes only dt.
    """

    containers = ()

    def __init__(self, x, y, kind, heading=None, bob_phase=None):
        super().__init__(x, y, SAUCER_RADIUS[kind])
        params = saucer_fire_params(kind)
        self.kind = kind
        self.hp = params["hp"]
        self.points = params["points"]
        self.fire_timer = params["fire_interval"]
        # heading: +1 crosses left→right, -1 right→left; random when unset.
        self.heading = heading if heading is not None else random.choice((-1.0, 1.0))
        self.velocity = pygame.Vector2(self.heading * params["speed"], 0)
        self.base = pygame.Vector2(x, y)
        self.bob_time = 0.0
        self.bob_phase = (
            random.uniform(0, 2 * math.pi) if bob_phase is None else bob_phase
        )
        self.despawned = False
        log_event("saucer_spawned", kind=kind)

    @property
    def bob_offset(self):
        """The sine bob's vertical offset at the current clock."""
        return math.sin(2 * math.pi * SAUCER_BOB_FREQUENCY * self.bob_time
                        + self.bob_phase) * SAUCER_BOB_AMPLITUDE

    def take_hit(self, hits=1):
        """One player shot's worth of damage. True when this call destroyed
        the saucer — the sweep pays the kill exactly once."""
        if not self.alive():
            return False
        self.hp -= hits
        if self.hp <= 0:
            self.kill()
            return True
        return False

    def fire(self, player, enemy_shots):
        """Real shots into the enemy group, aimed at the ship; the big
        kind spreads its volley around the aim direction."""
        params = saucer_fire_params(self.kind)
        aim = player.position - self.position
        if aim.length() == 0:
            aim = pygame.Vector2(0, -1)
        aim = aim.normalize()
        if params["spread"] > 1:
            angles = (
                -SAUCER_SPREAD_DEGREES,
                0.0,
                SAUCER_SPREAD_DEGREES,
            )[: params["spread"]]
        else:
            angles = (0.0,)
        for angle in angles:
            shot = SaucerShot(self.position.x, self.position.y)
            shot.velocity = aim.rotate(angle) * params["shot_speed"]
        sound.play(sound.SFX_SAUCER)

    def update(self, dt, player, enemy_shots):
        # Gravity rides where velocity already changes — the cross bends
        # toward any live well like every other body.
        self.velocity += pull_at(self.position) * dt
        self.base += self.velocity * dt
        self.bob_time += dt
        self.position = self.base + pygame.Vector2(0, self.bob_offset)

        if player is not None:
            self.fire_timer -= dt
            if self.fire_timer <= 0:
                self.fire_timer = saucer_fire_params(self.kind)["fire_interval"]
                self.fire(player, enemy_shots)

        if self.is_off_screen(SAUCER_RADIUS[self.kind] + SAUCER_EDGE_MARGIN):
            # A cull, never a paid kill — same reasoning as a drifting rock.
            self.despawned = True
            self.kill()

    def draw(self, screen):
        # Hostile silhouette: a body ring with a dome — distinct from every
        # friendly shape at a glance, in the hostile red.
        color = PALETTE["fringe_r"]
        pygame.draw.circle(screen, color, self.position, self.radius, LINE_WIDTH)
        pygame.draw.circle(
            screen, color, self.position - (0, self.radius // 2),
            self.radius // 2, LINE_WIDTH,
        )


def spawn_side_position(kind):
    """A random side-edge entry: x just outside the edge, y clear of the
    HUD strip and the shop panel — the bob must never dip into either."""
    y_low = SAUCER_BOB_AMPLITUDE + SAUCER_RADIUS[kind]
    y_high = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT - SAUCER_BOB_AMPLITUDE - SAUCER_RADIUS[kind]
    return (
        -SAUCER_RADIUS[kind] if random.random() < 0.5
        else SCREEN_WIDTH + SAUCER_RADIUS[kind],
        random.uniform(y_low, max(y_low, y_high)),
    )


class SaucerScheduler:
    """The spawn clock (insanity threats): from wave 2, one saucer every
    jittered interval, kinds alternating.

    The clock holds below the first wave, so a run's wave-1 warmup is
    unthreatened and the first saucer is never owed early.
    """

    def __init__(self):
        self.interval = SAUCER_SPAWN_INTERVAL_S
        self.jitter = SAUCER_SPAWN_JITTER_S
        self.timer = self.interval
        self.kind_index = 0

    def reset(self):
        """Full-restart hook: the clock and the alternation re-arm."""
        self.__init__()

    def update(self, dt, wave):
        """Tick the clock; the kind to spawn this frame, or None."""
        if wave < SAUCER_FIRST_WAVE:
            return None
        self.timer -= dt
        if self.timer > 0:
            return None
        self.timer = self.interval + random.uniform(-self.jitter, self.jitter)
        kind = next_saucer_kind(self.kind_index)
        self.kind_index += 1
        return kind