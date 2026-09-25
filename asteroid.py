import pygame
import random
from logger import log_event

import blackhole
from circleshape import CircleShape
from constants import (
    ASTEROID_KINDS,
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    ASTEROID_SPEED_MAX,
    ASTEROID_SPEED_MIN,
    BOSS_HP_PER_TIER,
    BOSS_POINTS,
    BOSS_RADIUS_TIERS,
    BOSS_WAVE_INTERVAL,
    CHIP_HEALTH_PER_TIER,
    LINE_WIDTH,
    MINION_CHECKPOINT_FRACTIONS,
    MINION_RADIUS_MULTIPLIER,
    PALETTE,
)
from hud import points_for

# Size-tier order for the palette lookup: tier 1 (small) → 3 (large).
ASTEROID_COLOR_KEYS = ("asteroid_s", "asteroid_m", "asteroid_l")


def asteroid_color(radius):
    """Pure palette hue for a rock, by size tier.

    Tiers mirror chip_threshold's round(radius / ASTEROID_MIN_RADIUS) and
    clamp to the ASTEROID_KINDS band, so any radius resolves to a real
    swatch — small pink up through large violet.
    """
    tier = min(ASTEROID_KINDS, max(1, round(radius / ASTEROID_MIN_RADIUS)))
    return PALETTE[ASTEROID_COLOR_KEYS[tier - 1]]


class Asteroid(CircleShape):
    # Time dilation (chrono powerup): the main loop writes the active
    # scale here every frame — class-level, so spawned and split rocks
    # dilate with the field, and expiry restores base speed by the same
    # write (no per-instance undo state to forget).
    speed_scale = 1.0

    def __init__(self, x, y, radius):
        super().__init__(x, y, radius)
        self.radius = radius
        # Click-chip state (idle core): accumulated click damage, plus the
        # despawn marker the main-loop destruction diff reads to tell a
        # cull (drifted off-screen) from a paid destruction. mintable is
        # the diff's second guard: bosses die through the same diff but
        # never mint credits (insanity threats).
        self.chip_damage = 0.0
        self.despawned = False
        self.mintable = True

    @property
    def chip_threshold(self):
        """Chip damage this rock absorbs before dying, by size tier."""
        tier = max(1, round(self.radius / ASTEROID_MIN_RADIUS))
        return tier * CHIP_HEALTH_PER_TIER

    def take_hit(self, hits=1):
        """One player-or-drone shot's worth of damage; True when this call
        destroyed the asteroid (the sweep pays the kill exactly once).

        The sweep routes every shot here instead of calling split() — the
        polymorphic seam the Boss overrides into an HP pool. A plain rock
        dies instantly, exactly as it always did."""
        if not self.alive():
            return False
        self.split()
        return True

    @property
    def kill_points(self):
        """Score paid for a shot kill, by type — the boss revalues itself."""
        return points_for(self.radius)

    def take_chip(self, amount):
        """Apply one click's chip damage; die through the normal split() path.

        Returns True when this call destroyed the asteroid. Shots never
        route here — they keep calling split() directly, so their
        instant-kill semantics (pinned by the sibling tests) hold untouched.
        """
        if not self.alive():
            return False
        self.chip_damage += amount
        if self.chip_damage >= self.chip_threshold:
            self.split()
            return True
        return False

    def draw(self, screen):
        pygame.draw.circle(
            screen,
            asteroid_color(self.radius),
            self.position,
            self.radius,
            LINE_WIDTH
        )
    def update(self, dt):
        # Insanity threats: live black holes bend every trajectory — the
        # pull rides the same velocity the chrono scale multiplies below.
        self.velocity += blackhole.pull_at(self.position) * dt
        # Chrono time dilation rides the frame step: the active scale
        # (1.0 baseline) is the class attribute the main loop publishes.
        self.position += self.velocity * self.speed_scale * dt
        if self.is_off_screen(ASTEROID_MAX_RADIUS):
            # Mark the cull before kill(): a rock that drifted off-screen
            # was never destroyed, so the idle diff poll must not mint for it.
            self.despawned = True
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


def boss_tier(wave, tiers=BOSS_RADIUS_TIERS):
    """Pure: the boss tier for a wave — wave // interval, capped at the
    largest tier the radius table knows. Lives beside the class so the
    field's wave_params and main's spawner share one formula."""
    return min(wave // BOSS_WAVE_INTERVAL, max(tiers))


class Boss(Asteroid):
    """A fifth-wave boss: one huge multi-hit rock with minion checkpoints.

    Shots soak its HP pool instead of splitting it; each checkpoint the
    pool crosses (70/40/15% of max HP) spawns two medium asteroids at the
    boss — the fight gets harder as it gets safer. It never mints credits,
    never drops pickups, and never dies to chip clicks; death (shots, the
    nuke, restart) flows through the ordinary kill() → destruction-diff
    path.
    """

    def __init__(self, x, y, tier):
        radius = ASTEROID_MIN_RADIUS * BOSS_RADIUS_TIERS[tier]
        super().__init__(x, y, radius)
        self.tier = tier
        self.max_hp = tier * BOSS_HP_PER_TIER
        self.hp = self.max_hp
        self.checkpoints_hit = 0
        # Never a credit wreck: the destruction diff skips non-mintable
        # bodies, so the boss pays score (BOSS_POINTS × multiplier) only.
        self.mintable = False

    def take_hit(self, hits=1):
        """One player shot's worth of damage; True only when this kills.

        Minion checkpoints: each threshold of MAX_HP the pool crosses
        (70/40/15%) spawns two mediums at the boss — a landed shot that
        doesn't kill still crosses thresholds honestly."""
        if not self.alive():
            return False
        self.hp -= hits
        log_event("boss_hit", hp=self.hp, max_hp=self.max_hp)
        if self.hp <= 0:
            self.kill()
            return True
        fraction = self.hp / self.max_hp
        while (
            self.checkpoints_hit < len(MINION_CHECKPOINT_FRACTIONS)
            and fraction < MINION_CHECKPOINT_FRACTIONS[self.checkpoints_hit]
        ):
            self.checkpoints_hit += 1
            self.spawn_minions()
        return False

    def spawn_minions(self):
        """Two medium asteroids at the boss, kicked outward in random
        directions so they don't overlap the fight's focus point."""
        for _ in range(2):
            minion = Asteroid(
                self.position.x, self.position.y,
                ASTEROID_MIN_RADIUS * MINION_RADIUS_MULTIPLIER,
            )
            direction = pygame.Vector2(0, 1).rotate(random.uniform(0, 360))
            minion.velocity = direction * random.uniform(
                ASTEROID_SPEED_MIN, ASTEROID_SPEED_MAX
            )

    def take_chip(self, amount):
        """Click chips never kill the boss — the fight is shot-HP only."""
        return False

    def split(self):
        """Death without children. Shots chip the HP pool instead of
        splitting, but the nuke and a restart still clear the boss through
        this same ordinary path — the boss is never exempted."""
        if not self.alive():
            return
        self.kill()

    @property
    def kill_points(self):
        return BOSS_POINTS
