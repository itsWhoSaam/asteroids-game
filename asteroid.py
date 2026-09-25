import pygame
import random
from logger import log_event

import blackhole
from circleshape import CircleShape
from comicfx import chromatic_circle, draw_cracks
from constants import (
    ASTEROID_KINDS,
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    ASTEROID_SPEED_MAX,
    ASTEROID_SPEED_MIN,
    BOSS_HIT_FLASH_S,
    BOSS_HP_PER_TIER,
    BOSS_POINTS,
    BOSS_RADIUS_TIERS,
    BOSS_RING_FRACTIONS,
    BOSS_WAVE_INTERVAL,
    CHIP_CRACK_FRACTIONS,
    CHIP_HEALTH_PER_TIER,
    LINE_WIDTH,
    MINION_CHECKPOINT_FRACTIONS,
    MINION_RADIUS_MULTIPLIER,
    MINE_BLAST_RADIUS,
    MINE_MARKER_BLINK_HZ,
    MINE_MARKER_COLOR,
    MINE_MARKER_RADIUS,
    MINE_SPAWN_CHANCE,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from hud import points_for
from stats import SOURCE_CLICK, SOURCE_IDLE

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


def chip_threshold_for(radius):
    """Chip damage a rock of this radius absorbs before dying, by size tier.

    The one formula the chip system reads: the Asteroid.chip_threshold
    property and the crack-stage gate both resolve through it, so a rock's
    last crack and its death always agree about where the threshold sits.
    """
    tier = max(1, round(radius / ASTEROID_MIN_RADIUS))
    return tier * CHIP_HEALTH_PER_TIER


def crack_stage(chip_damage, radius):
    """Pure crack stage 0-3 for a rock's accumulated chip damage.

    The stage counts how many CHIP_CRACK_FRACTIONS marks the damage has
    crossed as a fraction of the rock's chip threshold (crossing is
    inclusive: at the mark, the next stage shows), clamped to the table's
    length so an overshot damage reading can't run the web past its last
    stage. Zero for an untouched rock — and for split children, which
    start from fresh chip_damage and so draw uncracked again.
    """
    threshold = chip_threshold_for(radius)
    if threshold <= 0 or chip_damage <= 0:
        return 0
    fraction = chip_damage / threshold
    stage = sum(1 for mark in CHIP_CRACK_FRACTIONS if fraction >= mark)
    return min(stage, len(CHIP_CRACK_FRACTIONS))


class Asteroid(CircleShape):
    # Time dilation (chrono powerup): the main loop writes the active
    # scale here every frame — class-level, so spawned and split rocks
    # dilate with the field, and expiry restores base speed by the same
    # write (no per-instance undo state to forget).
    speed_scale = 1.0

    # The off-screen cull applies to every rock that isn't a fight's
    # anchor: subclasses that must not evaporate (the boss) veto it.
    cullable = True

    def __init__(self, x, y, radius):
        super().__init__(x, y, radius)
        self.radius = radius
        # Click-chip state (idle core): accumulated click damage, plus the
        # despawn marker the main-loop destruction diff reads to tell a
        # cull (drifted off-screen) from a paid destruction. mintable is
        # the diff's data guard — every body on the field mints unless a
        # future variant opts out; the boss's death is a paid destruction
        # like any other (the capstone payoff).
        self.chip_damage = 0.0
        # The crack web's pattern seed: fixed at birth so a drifting rock's
        # cracks stick to its body; deepening reveals more of the same web.
        self.crack_seed = random.randrange(2**32)
        self.despawned = False
        self.mintable = True
        # Run stats (run-stats PR): the kill source the mint poll reports —
        # take_chip flips it to "click" when a click kills; every other
        # kill site resets it to the idle default, so a rock chipped partway
        # and finished by a shot attributes to the shot.
        self.killed_by = SOURCE_IDLE

    @property
    def chip_threshold(self):
        """Chip damage this rock absorbs before dying, by size tier."""
        return chip_threshold_for(self.radius)

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
            self.killed_by = SOURCE_CLICK  # run stats: the click killed it
            self.split()
            return True
        return False

    def draw(self, screen):
        # Inked comic rock (V2): the tier hue stays the fill stroke; the
        # chromatic stack adds black ink and the red/cyan fringes around it.
        chromatic_circle(
            screen,
            asteroid_color(self.radius),
            self.position,
            self.radius,
            LINE_WIDTH
        )
        # Chip-damage cracks (Tier 2): the chipped hull wears its damage —
        # an ink web that deepens with the stage. Split children start from
        # fresh chip_damage, so the web resets on every split for free.
        stage = crack_stage(self.chip_damage, self.radius)
        if stage > 0:
            draw_cracks(screen, self.position, self.radius, stage, self.crack_seed)
    def update(self, dt):
        # Insanity threats: live black holes bend every trajectory — the
        # pull rides the same velocity the chrono scale multiplies below.
        self.velocity += blackhole.pull_at(self.position) * dt
        # Chrono time dilation rides the frame step: the active scale
        # (1.0 baseline) is the class attribute the main loop publishes.
        self.position += self.velocity * self.speed_scale * dt
        if self.is_off_screen(ASTEROID_MAX_RADIUS) and self.cullable:
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
    boss — the fight gets harder as it gets safer. A landed shot flashes
    the hull (the hit feedback) and every landed shot reads as layered
    armor: the multi-ring look that tells the boss apart from a big rock.
    It never dies to chip clicks, and its death — shots, the nuke, restart
    — flows through the ordinary kill() → destruction-diff path, minting
    credits like any wreck (the capstone payoff); the sweep adds a
    guaranteed chaos-table drop on top.
    """

    # The off-screen cull can't have the boss: a black-hole-dragged boss
    # slides along the screen edge (see update) instead of ending the wave
    # for free — no fight, no defeat, no event.
    cullable = False

    def __init__(self, x, y, tier):
        radius = ASTEROID_MIN_RADIUS * BOSS_RADIUS_TIERS[tier]
        super().__init__(x, y, radius)
        self.tier = tier
        self.max_hp = tier * BOSS_HP_PER_TIER
        self.hp = self.max_hp
        self.checkpoints_hit = 0
        # Hit feedback (capstone): a landed shot lights the hull for a
        # blink — dt-decayed in update, so a pause holds the flash too.
        self.hit_flash = 0.0

    def take_hit(self, hits=1):
        """One player shot's worth of damage; True only when this kills.

        Minion checkpoints: each threshold of MAX_HP the pool crosses
        (70/40/15%) spawns two mediums at the boss — a landed shot that
        doesn't kill still crosses thresholds honestly."""
        if not self.alive():
            return False
        self.hp -= hits
        self.hit_flash = BOSS_HIT_FLASH_S
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

    def update(self, dt):
        super().update(dt)
        # The cull can't have the boss (cullable = False), so a dragged
        # boss slides along the screen edge instead of leaving the fight:
        # black holes still shove it around (danger preserved, escape
        # denied), and the wave only advances when the boss dies.
        self.position.x = max(
            self.radius, min(SCREEN_WIDTH - self.radius, self.position.x)
        )
        self.position.y = max(
            self.radius, min(SCREEN_HEIGHT - self.radius, self.position.y)
        )
        if self.hit_flash > 0:
            self.hit_flash = max(0.0, self.hit_flash - dt)

    def draw(self, screen):
        # Layered-armor look (capstone): the inked rock base, then two
        # concentric inner rings in the hostile red that owns the HP bar —
        # one hue family for everything boss. The flash ring rides the
        # hull's outside while a landed shot's timer runs. Flat ink draws,
        # headless-safe (no per-pixel alpha).
        super().draw(screen)
        for fraction in BOSS_RING_FRACTIONS:
            pygame.draw.circle(
                screen,
                PALETTE["fringe_r"],
                self.position,
                max(1, int(self.radius * fraction)),
                width=LINE_WIDTH,
            )
        if self.hit_flash > 0:
            pygame.draw.circle(
                screen,
                PALETTE["hud_ink"],
                self.position,
                self.radius + LINE_WIDTH * 2,
                width=LINE_WIDTH * 2,
            )

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


# --- Mine asteroids (Tier 3) ---------------------------------------------------


def mine_spawn_rolls_in(roll, chance=MINE_SPAWN_CHANCE):
    """Pure: True when a field spawn's roll arms a mine.

    Strict <, the drops_powerup precedent — a roll exactly at the chance is
    a plain rock, so the boundary is pinned by tests, not float luck.
    """
    return roll < chance


def mine_marker_on(clock, period=1.0 / MINE_MARKER_BLINK_HZ):
    """Pure square wave: the danger marker shows for the first half of each
    blink period. The mine accumulates its own clock in update(dt) — sim
    time, so a paused or frozen frame holds the phase with everything else.
    """
    return (clock % period) < (period / 2)


def in_blast_radius(center, position, blast_radius):
    """Pure: True when position sits inside the blast circle.

    The rim is inclusive — "inside the radius" reads as at-or-within, and
    the inclusive side is the conservative one for a hazard.
    """
    return center.distance_to(position) <= blast_radius


def blast_victims(asteroids, center, blast_radius, exclude=None):
    """Pure selection: the live asteroids inside a blast circle, minus the
    excluded body (the detonating mine itself). One gate, so main's
    detonation and the tests agree on exactly who pays.
    """
    return [
        asteroid
        for asteroid in asteroids
        if asteroid.alive()
        and asteroid is not exclude
        and in_blast_radius(center, asteroid.position, blast_radius)
    ]


class Mine(Asteroid):
    """An armed rock (Tier 3): dark hull, blinking danger marker, and a
    blast when a SHOT kills it.

    It flies, culls, chips, and mints exactly like its host rock — the
    variant changes the death, not the drift. Shots route through the
    ordinary take_hit seam into split(), which for a mine is detonation
    without fission (no baby mines); the blast itself is wired in main's
    sweep — the one place a shot kill is known — because a mine stays a
    dumb body with no world refs (the Boss precedent).
    """

    def __init__(self, x, y, radius):
        super().__init__(x, y, radius)
        self.blink_clock = 0.0

    @property
    def blast_radius(self):
        return MINE_BLAST_RADIUS

    def update(self, dt):
        super().update(dt)
        self.blink_clock += dt

    def draw(self, screen):
        # A dark filled hull — distinctly not a tier hue — under the same
        # inked stroke every rock wears, then the blinking marker tells you
        # what this one is. Headless-safe: flat fills, no per-pixel alpha.
        pygame.draw.circle(screen, PALETTE["mine_hull"], self.position, self.radius)
        chromatic_circle(
            screen,
            PALETTE["mine_hull"],
            self.position,
            self.radius,
            LINE_WIDTH
        )
        if mine_marker_on(self.blink_clock):
            pygame.draw.circle(
                screen, MINE_MARKER_COLOR, self.position, MINE_MARKER_RADIUS
            )
        # Chipped mines wear cracks like any rock (free from the base draw).
        stage = crack_stage(self.chip_damage, self.radius)
        if stage > 0:
            draw_cracks(screen, self.position, self.radius, stage, self.crack_seed)

    def split(self):
        """Detonation, not fission: the mine dies without children. Every
        kill path — shots, the nuke, restart — lands here, so the
        destruction diff still sees an honest single-body wreck."""
        if not self.alive():
            return
        self.kill()

