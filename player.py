import math

import pygame
import blackhole
from circleshape import CircleShape
from constants import (
    BANK_FRACTION,
    BANK_RESPONSE_S,
    CANOPY_GLINT_FRACTION,
    CANOPY_GLINT_RADIUS,
    CANOPY_RADIUS_X,
    CANOPY_RADIUS_Y,
    DASH_COOLDOWN_S,
    DASH_IMPULSE,
    DASH_IFRAME_S,
    ENGINE_GLOW_HALF_WIDTH,
    ENGINE_GLOW_REACH_IDLE_PX,
    ENGINE_GLOW_REACH_THRUST_PX,
    ENGINE_GLOW_TAIL_INSET,
    ENGINE_GLOW_WIDTH_GAIN,
    HULL_GRADIENT_BANDS,
    LINE_WIDTH,
    PALETTE,
    PLAYER_BLINK_HZ,
    PLAYER_INVULNERABILITY_SECONDS,
    PLAYER_LINEAR_DAMPING,
    PLAYER_MASS,
    PLAYER_MAX_SPEED,
    PLAYER_RADIUS,
    PLAYER_RETRO_FACTOR,
    PLAYER_SHOOT_SPEED,
    PLAYER_THRUST_ACCEL,
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
    SHIP_SHADOW_OFFSET,
    THRUST_RESPONSE_S,
)
from comicfx import (
    chromatic_circle,
    chromatic_polygon,
    ellipse_points,
    hull_gradient_bands,
    light_direction,
    mix_colors,
)
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
        # Dash (insanity core): dash_timer is the cooldown clock for the
        # impulse dash() fires along the nose — the velocity it adds is
        # the same one the thrust integrator carries.
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
        # Semi-3D presentation clocks (this PR): the bank leans into the
        # current turn (-1..1) and the throttle drives the exhaust flame
        # (0..1). Both ease toward their per-frame targets in update() and
        # are never read by the sim.
        self.bank_level = 0.0
        self.thrust_level = 0.0

    @property
    def invulnerable(self):
        return self.invulnerability_timer > 0

    @property
    def inverse_mass(self):
        """The ship is a fixed small body (physics overhaul): one small
        rock's worth of inertia, so a large rock's hit shoves the ship
        hard while the rock barely notices."""
        return 1.0 / PLAYER_MASS

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
    def triangle(self, bank=0.0):
        """The hull's three points. bank (semi-3D, this PR): -1..1 from the
        presentation clock — the right vertex's offset scales by
        ±BANK_FRACTION so the ship leans into turns. bank=0 is the plan
        every existing caller and pin knows."""
        forward = pygame.Vector2(0, 1).rotate(self.rotation)
        right = pygame.Vector2(0, 1).rotate(self.rotation + 90) * self.radius / 1.5
        a = self.position + forward * self.radius
        b = self.position - forward * self.radius - right * (1 - BANK_FRACTION * bank)
        c = self.position - forward * self.radius + right * (1 + BANK_FRACTION * bank)
        return [a, b, c]

    def draw(self, screen):
        # Grace-window blink: skip the draw on alternate half-cycles so the
        # invulnerable ship flickers instead of sitting inside a rock unseen.
        if self.invulnerable and (self.invulnerability_timer * PLAYER_BLINK_HZ) % 1 >= 0.5:
            return
        points = self.triangle(self.bank_level)
        # Soft drop shadow (semi-3D): the hull's own shape offset in screen
        # space, filled in the shadow ink — the hull covers all but the
        # offset sliver, sitting the ship off the paper. The offset is
        # tuned (with the glow below) to stay inside the halo tripwire
        # band's 25px inner edge.
        shadow = [
            (x + SHIP_SHADOW_OFFSET[0], y + SHIP_SHADOW_OFFSET[1]) for x, y in points
        ]
        pygame.draw.polygon(screen, PALETTE["ship_drop_shadow"], shadow)
        # Gradient hull (semi-3D): the banded nose→tail cel fill — the
        # deep-indigo shade at the tail brightening to the lit cyan at the
        # nose, hard band edges like the rocks' shading.
        nose, tail_a, tail_b = points
        for quad, band in hull_gradient_bands(nose, tail_a, tail_b, HULL_GRADIENT_BANDS):
            pygame.draw.polygon(
                screen,
                mix_colors(PALETTE["ship_hull_shade"], PALETTE["ship"], band),
                quad,
            )
        # Canopy (semi-3D): a small dome near the centroid with a specular
        # glint dot toward the light — the strongest 3D cue at this scale.
        self._draw_canopy(screen, nose, tail_a, tail_b)
        # Inked comic hull (V2): black ink, chromatic fringes, cyan stroke —
        # unchanged, now tracing the banked hull over its fill.
        chromatic_polygon(
            screen,
            PALETTE["ship"],
            points,
            LINE_WIDTH
        )
        # Engine glow (semi-3D): the exhaust plume over the tail — drawn
        # after the ink stack so the idle ember stays readable past the
        # tail ink; its reach is tuned (with the shadow offset) to keep the
        # halo tripwire band paper.
        self._draw_engine_glow(screen)
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

    def _draw_engine_glow(self, screen):
        """The exhaust flame (semi-3D): a tapered plume behind the tail —
        its base inside the hull, its apex reaching ENGINE_GLOW_REACH_*
        from center with the throttle (an idle ember at rest, full flame
        ahead) — over one faded backing disc that melts it into the paper
        (the no-alpha fade; per-pixel alpha is off the table). Both stay
        under the halo band's 25px inner edge at full throttle."""
        nose_dir = pygame.Vector2(0, 1).rotate(self.rotation)
        reach = ENGINE_GLOW_REACH_IDLE_PX + (
            (ENGINE_GLOW_REACH_THRUST_PX - ENGINE_GLOW_REACH_IDLE_PX)
            * self.thrust_level
        )
        half_width = ENGINE_GLOW_HALF_WIDTH + ENGINE_GLOW_WIDTH_GAIN * self.thrust_level
        base_center = self.position - nose_dir * (self.radius - ENGINE_GLOW_TAIL_INSET)
        apex = self.position - nose_dir * reach
        right = pygame.Vector2(0, 1).rotate(self.rotation + 90)
        pygame.draw.circle(
            screen,
            mix_colors(PALETTE["engine_glow"], PALETTE["paper"], 0.55),
            (base_center.x, base_center.y),
            max(1, int(half_width + 2)),
        )
        pygame.draw.polygon(
            screen,
            PALETTE["engine_glow"],
            [
                (
                    base_center.x + right.x * half_width,
                    base_center.y + right.y * half_width,
                ),
                (
                    base_center.x - right.x * half_width,
                    base_center.y - right.y * half_width,
                ),
                (apex.x, apex.y),
            ],
        )

    def _draw_canopy(self, screen, nose, tail_a, tail_b):
        """The cockpit (semi-3D): a small ellipse at the hull's centroid,
        its long axis across the ship, with the specular glint dot thrown
        toward the shared light. Pure fills — headless-safe."""
        centroid = (nose + tail_a + tail_b) / 3
        canopy = ellipse_points(
            centroid,
            self.radius * CANOPY_RADIUS_X,
            self.radius * CANOPY_RADIUS_Y,
            self.rotation + 90,
        )
        pygame.draw.polygon(screen, PALETTE["ship_canopy"], canopy)
        glint = centroid + light_direction() * self.radius * CANOPY_GLINT_FRACTION
        pygame.draw.circle(
            screen,
            PALETTE["hud_ink"],
            (glint.x, glint.y),
            CANOPY_GLINT_RADIUS,
        )

    def rotate(self, dt):
        self.rotation += PLAYER_TURN_SPEED * dt

    def dash(self):
        """SHIFT (insanity core): an impulse along the nose with brief
        i-frames. False while cooling down.

        The impulse composes with the momentum the ship already carries —
        thrust velocity plus dash, capped by update's speed ceiling — and
        ordinary linear damping bleeds the total back down: the dash no
        longer owns or zeroes velocity. I-frames ride the existing
        invulnerability timer via max() — a respawn grace is never
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
        # A frozen frame (hit-stop, pause) steps dt=0: integrate nothing —
        # no thrust, no damping, no pull, no cooldown ticks, no trigger
        # pull. Everything below advances only on positive dt.
        if dt <= 0:
            return
        keys = pygame.key.get_pressed()
        self.shot_cooldown_timer -= dt
        self.invulnerability_timer -= dt
        self._tick_powerups(dt)

        # Dash cooldown (insanity core): the clock drains on sim time. The
        # impulse it gates composes with the ship's carried momentum, and
        # ordinary linear damping — not a hard zero — hands normal
        # handling back when the glide bleeds out.
        self.dash_timer = max(0.0, self.dash_timer - dt)

        # REVERSE curse (insanity chaos): one sign flips every answer the
        # controls get — the same keys, the backwards ship. The dash is not
        # flipped: it fires along the nose, which the cursed steering aims.
        sign = -1.0 if self.cursed_reverse else 1.0
        rotation_before = self.rotation
        if keys[pygame.K_a]:
            self.rotate(-dt * sign)
        if keys[pygame.K_d]:
            self.rotate(dt * sign)

        # Newtonian thrust (physics overhaul): W accelerates along the nose,
        # S retro-thrusts at a fraction of it, and the velocity they build
        # persists between frames — releasing the keys leaves the ship
        # coasting on its momentum.
        nose = pygame.Vector2(0, 1).rotate(self.rotation)
        accel = pygame.Vector2(0, 0)
        if keys[pygame.K_w]:
            accel += nose * PLAYER_THRUST_ACCEL
        if keys[pygame.K_s]:
            accel -= nose * PLAYER_THRUST_ACCEL * PLAYER_RETRO_FACTOR
        self.velocity += accel * sign * dt
        # Insanity threats: gravity accelerates the ship toward any live
        # well at half strength (BLACK_HOLE_PLAYER_FACTOR) — integrated
        # into velocity like every other body in the field now, not a
        # position drift.
        self.velocity += blackhole.pull_at(self.position, player=True) * dt
        # Light linear damping: gentle space drag that bleeds all of the
        # ship's momentum — thrust, dash, pull — back toward rest.
        self.velocity *= math.exp(-PLAYER_LINEAR_DAMPING * dt)
        # Speed ceiling: anti-tunnel by arithmetic — the worst clamped frame
        # moves PLAYER_MAX_SPEED * MAX_DT = 36 px, inside the 40 px minimum
        # contact overlap, so overlap can't be jumped over. The guard keeps
        # the clamp off a stationary ship (pygame refuses zero-length
        # clamping, and a zero vector is under the cap anyway).
        if self.velocity.length() > PLAYER_MAX_SPEED:
            self.velocity = self.velocity.clamp_magnitude(PLAYER_MAX_SPEED)
        self.position += self.velocity * dt
        # Ship-only wrap: the ship is the one body that re-enters the
        # opposite edge — rocks, shots, pickups, and saucers cull, and the
        # destruction diff depends on that. The hull radius is the margin:
        # the ship fully leaves one side before re-entering the other.
        self.wrap()

        # Semi-3D presentation clocks: the bank tracks this frame's
        # rotation delta (a full-rate turn banks fully), the throttle
        # tracks forward thrust or a dash. Both ease toward their targets;
        # the dt<=0 early return above already holds them on frozen frames.
        # The sim never reads either field.
        turn_fraction = (self.rotation - rotation_before) / (PLAYER_TURN_SPEED * dt)
        bank_target = max(-1.0, min(1.0, turn_fraction))
        self.bank_level += (bank_target - self.bank_level) * min(
            1.0, dt * BANK_RESPONSE_S
        )
        forward_input = (
            (keys[pygame.K_w] and not self.cursed_reverse)
            or (keys[pygame.K_s] and self.cursed_reverse)
        )
        throttle_target = 1.0 if forward_input or self.dash_timer > 0 else 0.0
        self.thrust_level += (throttle_target - self.thrust_level) * min(
            1.0, dt * THRUST_RESPONSE_S
        )

        # A held space fires on the cooldown clock. The dt>0 guard above
        # already keeps a frozen frame from machine-gunning stacked shots
        # at a paused cooldown.
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

    def wrap(self):
        """Ship-only screen wrap (physics overhaul): the hull radius is the
        margin — the ship fully leaves one side before re-entering the
        other. Rocks, shots, pickups, and saucers cull instead, and the
        destruction diff depends on that, so wrap never leaves the ship."""
        margin = self.radius
        if self.position.x < -margin:
            self.position.x = SCREEN_WIDTH + margin
        elif self.position.x > SCREEN_WIDTH + margin:
            self.position.x = -margin
        if self.position.y < -margin:
            self.position.y = SCREEN_HEIGHT + margin
        elif self.position.y > SCREEN_HEIGHT + margin:
            self.position.y = -margin
