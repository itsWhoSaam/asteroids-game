import pygame
import blackhole
from circleshape import CircleShape
from constants import (
    DASH_COOLDOWN_S,
    DASH_DECAY,
    DASH_IMPULSE,
    DASH_IFRAME_S,
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
from logger import log_event
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
        # Dash (insanity core): the impulse is the ship's only velocity —
        # movement is otherwise direct position stepping — and dash_timer
        # is the shared cooldown + decay clock.
        self.velocity = pygame.Vector2(0, 0)
        self.dash_timer = 0.0
        # Bomb pickup (insanity chaos): main injects the field-clear
        # callback — the ship never owns the world. None (tests, callback
        # not yet wired) makes the bomb a safe no-op.
        self.bomb_field = None
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
    def has_pierce(self):
        """PIERCE active (insanity chaos): shots drill through plain rocks
        this frame instead of dying on impact."""
        return self.powerup_timers.get(PowerUpType.PIERCE.value, 0.0) > 0

    @property
    def has_homing(self):
        """HOMING active (insanity chaos): every friendly shot steers toward
        the nearest asteroid while the timer runs."""
        return self.powerup_timers.get(PowerUpType.HOMING.value, 0.0) > 0

    @property
    def cursed_reverse(self):
        """REVERSE curse (insanity chaos): the controls answer backwards
        while its clock runs — steering, thrust, and brake all flip."""
        return self.powerup_timers.get(PowerUpType.REVERSE.value, 0.0) > 0

    @property
    def shielded(self):
        """A shield charge is stocked: the next hit is absorbed (F4)."""
        return self.shield_hits > 0

    @property
    def has_magnet(self):
        """MAGNET active (Tier 3): nearby pickups and credit floats are
        pulled this frame; zero otherwise."""
        return self.magnet_timer > 0

    @property
    def magnet_timer(self):
        """Seconds left on the magnet's clock — 0.0 when inactive. The
        HUD's hidden-while-zero slot reads this."""
        return self.powerup_timers.get(PowerUpType.MAGNET.value, 0.0)

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
        the idle-economy follow-up retunes constants, not this code.

        Insanity chaos adds the instant types — neither arms a clock:
        the bomb fires its injected field-clear callback now, and the
        disarm reveal strips everything running."""
        if kind is PowerUpType.BOMB:
            if self.bomb_field is not None:
                self.bomb_field()
            return
        if kind is PowerUpType.DISARM:
            # The reveal sting: the shield's unspent charges and every
            # running effect timer evaporate at once — a lucky stack dies
            # the moment the curse shows itself.
            self.powerup_timers.clear()
            self.shield_hits = 0
            return
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

    def dash(self):
        """SHIFT (insanity core): an impulse along the nose with brief
        i-frames. False while cooling down.

        The impulse is the ship's only velocity, and it owns its decay
        (update bleeds it while the cooldown clock runs). I-frames ride the
        existing invulnerability timer via max() — a respawn grace is never
        shortened, and the blink draw already shows the safe window. The
        combo break is the caller's wiring (main.try_dash): the ship does
        not own run state."""
        if self.dash_timer > 0:
            return False
        self.dash_timer = DASH_COOLDOWN_S
        self.velocity += pygame.Vector2(0, 1).rotate(self.rotation) * DASH_IMPULSE
        self.invulnerability_timer = max(self.invulnerability_timer, DASH_IFRAME_S)
        # F6: sound.play never raises — a no-op without a mixer or muted.
        sound.play(sound.SFX_DASH)
        log_event("dash_used")
        return True

    def update(self, dt):
        keys = pygame.key.get_pressed()
        self.shot_cooldown_timer -= dt
        self.invulnerability_timer -= dt
        self._tick_powerups(dt)

        # Dash glide (insanity core): the impulse bleeds off exponentially
        # while the cooldown clock runs — the visible glide is the first
        # DASH_DECAY_S — and when the clock empties, the velocity is
        # zeroed so the ship handles normally again. A frozen frame
        # (hit-stop) steps dt=0: no glide, no decay, no cooldown tick.
        if self.dash_timer > 0:
            self.dash_timer = max(0.0, self.dash_timer - dt)
            self.position += self.velocity * dt
            if self.velocity.length() > 0:
                self.velocity *= DASH_DECAY ** dt
            if self.dash_timer == 0:
                self.velocity.update((0, 0))  # glide over: clean handback

        # REVERSE curse (insanity chaos): one sign flips every answer the
        # controls get — the same keys, the backwards ship. The dash is not
        # flipped: it fires along the nose, which the cursed steering aims.
        sign = -1.0 if self.cursed_reverse else 1.0
        if keys[pygame.K_a]:
            self.rotate(-dt * sign)
        if keys[pygame.K_d]:
            self.rotate(dt * sign)
        if keys[pygame.K_w]:
            self.move(dt * sign)
        if keys[pygame.K_s]:
            self.move(-dt * sign)
        # Insanity threats: gravity drifts the ship toward any live well at
        # half strength (BLACK_HOLE_PLAYER_FACTOR) — a position drift, not
        # velocity: the dash owns the only velocity the ship has.
        self.position += blackhole.pull_at(self.position, player=True) * dt
        # A held space fires on the cooldown clock, which only advances on
        # sim time. A frozen frame (hit-stop) steps dt=0: firing here would
        # machine-gun stacked shots at a paused cooldown, so a zero-dt
        # frame never pulls the trigger.
        if keys[pygame.K_SPACE] and dt > 0:
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