"""Idle automation: one auto-turret per Drones level, plus the offline HUD.

DroneTurrets fire REAL Shot instances into the existing shots group on a
DRONE_FIRE_INTERVAL_S cadence, aimed at the nearest asteroid — so drone
kills flow through the same collision sweep, the same destruction diff,
and the same Economy.mint path as player shots. There is no separate drone
ledger: one destruction pipeline pays every source.

Time away still pays through Economy.apply_offline (capped, half rate);
this module supplies only the fleet's estimated rate and the fading
'Offline earnings +N' HUD line.
"""

import pygame

import sound

from constants import (
    DRONE_CREDITS_PER_SHOT,
    DRONE_FIRE_INTERVAL_S,
    DRONE_MARKER_COLOR,
    DRONE_MARKER_RADIUS,
    DRONE_ORBIT_RADIUS,
    DRONE_ORBIT_SPEED,
    DRONE_SHOT_SPEED,
    FLOAT_COLOR,
    HUD_LINE_STEP,
    HUD_MARGIN,
    LINE_WIDTH,
    OFFLINE_BANNER_SECONDS,
)
from hud import hud_font
from shot import Shot


def nearest_asteroid(asteroids, position):
    """The closest asteroid to ``position``, or None when the field is empty."""
    best = None
    best_dist = float("inf")
    for asteroid in asteroids:
        dist = asteroid.position.distance_to(position)
        if dist < best_dist:
            best, best_dist = asteroid, dist
    return best


def drone_dps(level):
    """Estimated offline credits/second for a Drones level.

    One instant-kill shot per DRONE_FIRE_INTERVAL_S worth the
    DRONE_CREDITS_PER_SHOT estimate: the grant can't see live rock radii,
    so it prices the average kill, not the live points table.
    """
    if level <= 0:
        return 0.0
    return level * DRONE_CREDITS_PER_SHOT / DRONE_FIRE_INTERVAL_S


class DroneTurret:
    """One stationary auto-turret riding an orbit ring around the ship.

    Fires a real Shot every DRONE_FIRE_INTERVAL_S — instant-kill split on
    hit, exactly the player shot's semantics — so the pinned collision
    tests see nothing new in the pipeline. With no asteroid to aim at it
    fires straight ahead of the ship's nose.
    """

    def __init__(self, index, count):
        # Evenly spaced slots around the orbit. The first shot is staggered
        # inside the first interval (never on frame one) so N turrets don't
        # volley in lockstep; after firing, each holds a steady cadence.
        self.orbit_angle = (360.0 * index / count) % 360.0
        self.fire_timer = DRONE_FIRE_INTERVAL_S * (index + 1) / (count + 1)

    def muzzle(self, player):
        """Current marker (and muzzle) position on the orbit ring."""
        offset = pygame.Vector2(0, 1).rotate(self.orbit_angle) * DRONE_ORBIT_RADIUS
        return player.position + offset

    def aim(self, player, asteroids):
        """Unit fire direction: at the nearest asteroid, or straight ahead."""
        muzzle = self.muzzle(player)
        target = nearest_asteroid(asteroids, muzzle)
        if target is not None:
            direction = target.position - muzzle
            if direction.length() > 0:
                return direction.normalize()
        return pygame.Vector2(0, 1).rotate(player.rotation)

    def fire(self, player, asteroids, shots):
        """One real Shot into the shared group — the player-shot pipeline."""
        muzzle = self.muzzle(player)
        shot = Shot(muzzle.x, muzzle.y)
        shot.velocity = self.aim(player, asteroids) * DRONE_SHOT_SPEED
        shot.from_drone = True  # run stats: turret fire, not the player's trigger
        sound.play(sound.SFX_DRONE_FIRE)  # extra SFX: the turret's own pew

    def update(self, dt, player, asteroids, shots):
        self.orbit_angle = (self.orbit_angle + DRONE_ORBIT_SPEED * dt) % 360.0
        self.fire_timer -= dt
        if self.fire_timer > 0:
            return
        # += keeps any overshoot, so the cadence stays a true interval.
        self.fire_timer += DRONE_FIRE_INTERVAL_S
        self.fire(player, asteroids, shots)

    def draw(self, screen, player):
        pygame.draw.circle(
            screen,
            DRONE_MARKER_COLOR,
            self.muzzle(player),
            DRONE_MARKER_RADIUS,
            LINE_WIDTH,
        )


class DroneBay:
    """The fleet: turret count synced to the Economy's Drones level.

    The bay keeps no state of its own beyond the turret list — the level
    in economy.levels['drone'] is the single source of truth, re-read
    every frame, so a purchase grows the fleet and zero levels field
    none (and cost nothing).
    """

    def __init__(self, economy):
        self.economy = economy
        self.turrets = []

    def sync(self):
        """Match the turret list to the Drones level, growing or shrinking."""
        level = self.economy.levels["drone"]
        while len(self.turrets) < level:
            self.turrets.append(DroneTurret(len(self.turrets), level))
        while len(self.turrets) > level:
            self.turrets.pop()

    def update(self, dt, player, asteroids, shots):
        self.sync()
        for turret in self.turrets:
            turret.update(dt, player, asteroids, shots)

    def draw(self, screen, player):
        for turret in self.turrets:
            turret.draw(screen, player)


class OfflineBanner:
    """The one-time 'Offline earnings +N' HUD line, fading out.

    A plain HUD object, not a sprite: it sits in a fixed slot under the
    credits readout, steps its own lifetime on dt, and draws nothing once
    the fade completes. A zero grant (fresh install, no timestamp) never
    shows at all.
    """

    def __init__(self, amount):
        self.amount = amount
        self.lifetime = OFFLINE_BANNER_SECONDS if amount > 0 else 0.0

    def update(self, dt):
        self.lifetime -= dt

    def draw(self, screen):
        if self.lifetime <= 0:
            return
        surface = hud_font().render(
            f"Offline earnings +{int(self.amount)}", True, FLOAT_COLOR
        )
        fade = max(0.0, min(1.0, self.lifetime / OFFLINE_BANNER_SECONDS))
        surface.set_alpha(int(fade * 255))
        screen.blit(
            surface, (HUD_MARGIN, HUD_MARGIN + 4 * HUD_LINE_STEP)
        )
