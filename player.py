import pygame
from circleshape import CircleShape
from constants import (
    LINE_WIDTH,
    PALETTE,
    PLAYER_BLINK_HZ,
    PLAYER_INVULNERABILITY_SECONDS,
    PLAYER_RADIUS,
    PLAYER_SHOOT_SPEED,
    PLAYER_SPEED,
    PLAYER_TURN_SPEED,
    PLAYER_SHOOT_COOLDOWN_SECONDS,
    PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS,
    POWERUP_DURATION_S,
    POWERUP_RAPID_COOLDOWN_MULT,
    POWERUP_SHIELD_HITS,
    POWERUP_SHIELD_RING_GAP,
    POWERUP_TRIPLE_SPREAD,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from comicfx import chromatic_circle, chromatic_polygon
from powerups import PowerUpType

import sound
from shot import Shot


class Player(CircleShape):
    def __init__(self, x, y):
        super().__init__(x, y, PLAYER_RADIUS )
        self.shot_cooldown_timer = 0
        # Shot-rate multiplier the shop mutates (Fire-rate levels); the
        # stock ship fires on the bare constant.
        self.cooldown_mult = 1.0
        # Grace window after a respawn: dt-decremented like shot_cooldown_timer.
        self.invulnerability_timer = 0.0
        # Timed pickups (F4): PowerUpType value -> seconds remaining,
        # dt-decremented like every timer on this class. The shield
        # additionally stocks POWERUP_SHIELD_HITS charges.
        self.powerup_timers = {}
        self.shield_hits = 0
        self.rotation = 0
        # Run-stat sink (run-stats PR): Game injects the run's counters at
        # construction — the player is built before the Game exists, so the
        # attribute starts None and every recorder call guards on it.
        self.stats = None

    @property
    def invulnerable(self):
        return self.invulnerability_timer > 0

    @property
    def has_rapid(self):
        """RAPID active: the shoot cooldown is cut for this frame (F4)."""
        return self.powerup_timers.get(PowerUpType.RAPID.value, 0.0) > 0

    @property
    def has_triple(self):
        """TRIPLE active: shots leave in a three-way spread this frame (F4)."""
        return self.powerup_timers.get(PowerUpType.TRIPLE.value, 0.0) > 0

    @property
    def shielded(self):
        """A shield charge is stocked: the next hit is absorbed (F4)."""
        return self.shield_hits > 0

    def respawn(self):
        """Center the ship, zero its velocity, grant the grace window.

        Invulnerability is what lets a respawning ship sit safely inside an
        asteroid it materialized on — the collision sweep checks it before
        resolving any hit.
        """
        self.position = pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
        self.velocity = pygame.Vector2(0, 0)
        self.invulnerability_timer = PLAYER_INVULNERABILITY_SECONDS

    def activate_powerup(self, kind):
        """Turn a collected pickup on: (re)arm its duration from the
        constants table; the shield stocks its hit count. Data-driven (F4):
        the idle-economy follow-up retunes constants, not this code."""
        self.powerup_timers[kind.value] = POWERUP_DURATION_S[kind.value]
        if kind is PowerUpType.SHIELD:
            self.shield_hits = POWERUP_SHIELD_HITS

    def absorb_hit(self):
        """Spend one shield charge on an incoming hit. True when absorbed.

        Game.player_hit routes every hit through here first, so life loss
        and respawn stay in one place: an absorbed hit skips both."""
        if not self.shielded:
            return False
        self.shield_hits -= 1
        return True

    def grant_shield(self, charges=1):
        """Stock shield absorbs outright (milestone rewards): kept until
        spent, with no duration clock — unlike a drop-shield, whose timer
        wipes the pool when it runs out. One shield pool on purpose: the
        ring draw and absorb_hit read shield_hits alone."""
        self.shield_hits += charges

    def clear_powerups(self):
        """Wipe every active effect — part of the full-restart reset (F4)."""
        self.powerup_timers = {}
        self.shield_hits = 0

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
        # Inked comic hull (V2): black ink, chromatic fringes, cyan stroke.
        chromatic_polygon(
            screen,
            PALETTE["ship"],
            self.triangle(),
            LINE_WIDTH
        )
        # Shield ring (F4): a stocked charge shows outside the hull, so the
        # player can see the next hit will be absorbed. Blinking with the
        # ship above keeps the ring honest during the grace window too.
        if self.shielded:
            chromatic_circle(
                screen,
                PALETTE["powerup_shield"],
                self.position,
                self.radius + POWERUP_SHIELD_RING_GAP,
                LINE_WIDTH,
            )

    def rotate(self, dt):
        self.rotation += PLAYER_TURN_SPEED * dt

    def update(self, dt):
        keys = pygame.key.get_pressed()
        self.shot_cooldown_timer -= dt
        self.invulnerability_timer -= dt
        self._tick_powerups(dt)

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

    def _tick_powerups(self, dt):
        """Expire timed effects: decrement each duration; a type whose clock
        runs out loses its effect — the shield also loses its unspent hits."""
        for kind, remaining in list(self.powerup_timers.items()):
            remaining -= dt
            if remaining > 0:
                self.powerup_timers[kind] = remaining
            else:
                del self.powerup_timers[kind]
                if kind == PowerUpType.SHIELD.value:
                    self.shield_hits = 0

    def shoot(self):
        if self.shot_cooldown_timer > 0:
            return
        # Fire-rate levels scale the cooldown (shop) and RAPID cuts it
        # further (F4); the floor keeps a maxed setup from turning the ship
        # into a hitscan laser.
        self.shot_cooldown_timer = max(
            PLAYER_SHOOT_COOLDOWN_SECONDS
            * self.cooldown_mult
            * (POWERUP_RAPID_COOLDOWN_MULT if self.has_rapid else 1.0),
            PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS,
        )
        # F6: one blip per trigger pull, even on a TRIPLE volley. A no-op
        # whenever audio is unavailable or muted — sound.play never raises.
        sound.play(sound.SFX_SHOOT)
        if self.has_triple:
            # Three-way spread: the center shot plus one on each side (F4).
            for spread in (-POWERUP_TRIPLE_SPREAD, 0.0, POWERUP_TRIPLE_SPREAD):
                self._fire(spread)
        else:
            self._fire(0.0)

    def _fire(self, spread_degrees):
        shot = Shot(self.position.x, self.position.y)
        shot.velocity = (
            pygame.Vector2(0, 1).rotate(self.rotation + spread_degrees)
            * PLAYER_SHOOT_SPEED
        )
        # Run stats (run-stats PR): one bullet left the ship. Counted here,
        # per bullet — a TRIPLE volley fires three, so the summary's
        # hit/fired accuracy can never pass 100%.
        if self.stats is not None:
            self.stats.record_shot()

    def move (self, dt):
        unit_vector = pygame.Vector2(0, 1)
        rotated_vector = unit_vector.rotate(self.rotation)
        rotated_with_speed_vector = rotated_vector * PLAYER_SPEED * dt
        self.position += rotated_with_speed_vector