SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
PLAYER_RADIUS = 20
LINE_WIDTH = 2
PLAYER_TURN_SPEED = 300
PLAYER_SPEED = 200

ASTEROID_MIN_RADIUS = 20
ASTEROID_KINDS = 3
ASTEROID_SPAWN_RATE_SECONDS = 0.8
ASTEROID_MAX_RADIUS = ASTEROID_MIN_RADIUS * ASTEROID_KINDS

SHOT_RADIUS = 5
PLAYER_SHOOT_SPEED = 500

PLAYER_SHOOT_COOLDOWN_SECONDS = 0.3

# Upper bound on a single frame's delta: absorbs stalls (alt-tab, window
# drag) so entities never move far enough to tunnel through a collision.
MAX_DT = 0.1

# Scoring by size tier (engagement F1): smaller rocks are worth more.
SCORE_LARGE = 20
SCORE_MEDIUM = 50
SCORE_SMALL = 100

# Lives & respawn (engagement F2): a hit costs a life, not the process.
PLAYER_START_LIVES = 3
PLAYER_INVULNERABILITY_SECONDS = 2.0
PLAYER_BLINK_HZ = 4  # the grace-window blink toggles at this rate

# Game-over overlay (engagement F2), centered on the screen.
GAME_OVER_FONT_SIZE = 48
GAME_OVER_LINE_STEP = 60

# Wave progression (engagement F3): clearing the field starts the next wave,
# tightening the spawn cadence and shifting the asteroid speed band up. The
# wave-1 bases are the 0.8s cadence and 40–100 px/s band the field used to
# hardcode inline.
WAVE_SPAWN_DECAY = 0.9            # spawn interval multiplier per wave
WAVE_SPAWN_INTERVAL_FLOOR = 0.3   # seconds — waves never spawn faster than this
ASTEROID_SPEED_MIN = 40           # wave-1 minimum asteroid speed (px/s)
ASTEROID_SPEED_MAX = 100          # wave-1 maximum asteroid speed (px/s)
WAVE_SPEED_MIN_STEP = 10          # minimum-speed increase per wave
WAVE_SPEED_MAX_STEP = 15          # maximum-speed increase per wave
WAVE_BANNER_SECONDS = 2.0         # WAVE n banner flash duration

# HUD text (engagement F1), top-left corner.
HUD_FONT_SIZE = 28
HUD_MARGIN = 12
HUD_LINE_STEP = 34
HUD_COLOR = "white"

# --- Idle economy core ---------------------------------------------------
# All balance numbers here are playtest starting values from the idle spec;
# none is structural. The shop PR turns them into purchasable controls.

# Chip damage per click. The Nanoblade upgrade multiplies this in the shop
# PR; the economy core wires it through with no multiplier yet.
CLICK_DAMAGE_BASE = 1.0

# Chip health per size tier (tier = radius / ASTEROID_MIN_RADIUS): a small
# rock absorbs one tier's worth (~3 base clicks), a large three tiers'
# (~9). Crossing the threshold dies through the normal split() path; shots
# bypass chips entirely and keep their instant-kill split().
CHIP_HEALTH_PER_TIER = 3.0

# Upgrade cost curves: cost(level) = base * growth ** level. Exponential on
# purpose — prices must always outpace linear income so the shop always has
# a next goal. Purchases land in the shop PR.
UPGRADE_COSTS = {
    "nanoblade": (10.0, 1.75),  # click damage
    "fire_rate": (25.0, 1.90),  # shot cooldown
    "income": (50.0, 2.00),  # credit multiplier
    "drone": (100.0, 2.20),  # idle turret count
}

# Floating '+N' credit numbers over fresh wrecks (dt-timer lifetime).
FLOAT_FONT_SIZE = 20
FLOAT_LIFETIME_SECONDS = 1.0
FLOAT_RISE_SPEED = 40.0  # px/s upward
FLOAT_COLOR = "yellow"

# Idle persistence: autosave cadence; quitting also saves. The offline
# payout cap reads idle_last_seen once the drones PR lands.
IDLE_AUTOSAVE_SECONDS = 30.0

# --- Upgrade shop ---------------------------------------------------------
# Multiplier steps applied per purchased level; the cost curves themselves
# live in UPGRADE_COSTS above (the Economy owns the curve, the shop buys
# through it). Spec-table values — playtest starting points, none structural.

NANOBLADE_MULT_PER_LEVEL = 1.8  # click chip damage ×1.8 per Nanoblade level
FIRE_RATE_MULT_PER_LEVEL = 0.88  # shot cooldown ×0.88 per Fire-rate level
# The cooldown never drops below this, however many Fire-rate levels are bought.
PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS = 0.03
INCOME_MULT_PER_LEVEL = 1.15  # credit payouts ×1.15 per Income level

# Bottom shop panel: one strip across the screen width, below the play
# field — clear of the top-left score HUD (F1) and the centered game-over
# overlay (F2).
SHOP_FONT_SIZE = 18
SHOP_PANEL_HEIGHT = 64
SHOP_CELL_PADDING = 10
SHOP_LINE_STEP = 22
SHOP_PANEL_BG = (16, 16, 28)
SHOP_PANEL_BORDER = (70, 70, 90)
SHOP_DIM_COLOR = (100, 100, 100)  # an upgrade the ledger can't pay for yet
SHOP_BRIGHT_COLOR = (255, 230, 120)  # affordable — the next purchase glows

# --- Idle drones & offline earnings ---------------------------------------
# One auto-turret per Drones level. Turrets fire REAL Shot instances into
# the existing shots group, so drone kills flow through the same collision
# sweep, the same destruction diff, and the same Economy.mint path as
# player shots — one destruction pipeline pays every source.

DRONE_FIRE_INTERVAL_S = 1.5  # per-turret cadence: one instant-kill Shot
DRONE_SHOT_SPEED = 500  # px/s — matches the player's shot feel
DRONE_ORBIT_RADIUS = 36  # px from ship center; markers clear PLAYER_RADIUS
DRONE_ORBIT_SPEED = 72.0  # deg/s — one lap every 5 s, purely visual
DRONE_MARKER_RADIUS = 5  # px — the small distinct turret marker
DRONE_MARKER_COLOR = (90, 220, 200)  # teal — distinct from ship, shots, floats

# Offline payout estimate: a drone shot kills a rock of unknown size, so the
# grant prices the medium tier per shot instead of reading the live table.
DRONE_CREDITS_PER_SHOT = 50.0

# Time away still pays, per the spec's balance table: capped at 8 hours and
# paid at half rate. The boot grant reads idle_last_seen once per launch;
# the regular autosave keeps the stamp fresh while playing.
OFFLINE_CAP_SECONDS = 8 * 3600
OFFLINE_RATE = 0.5

# The one-time 'Offline earnings +N' HUD line fades out over this long.
OFFLINE_BANNER_SECONDS = 4.0

# Power-ups (engagement F4): a destroyed non-small rock can drop a timed
# pickup. Effects are data-driven — every duration and magnitude lives in
# these tables (keys match PowerUpType values in powerups.py) so the
# idle-economy follow-up can retune or extend them without touching
# gameplay code.
POWERUP_DROP_CHANCE = 0.15         # chance a destroyed non-small rock drops one
POWERUP_DURATION_S = {
    "shield": 8.0,
    "rapid": 8.0,
    "triple": 8.0,
}
POWERUP_RAPID_COOLDOWN_MULT = 0.4  # RAPID multiplies the shoot cooldown
POWERUP_TRIPLE_SPREAD = 20.0       # degrees between the three TRIPLE shots
POWERUP_SHIELD_HITS = 1            # hits one shield absorbs
POWERUP_RADIUS = 14
POWERUP_DRIFT_SPEED = 30           # px/s — pickups drift, they don't sit still
POWERUP_FONT_SIZE = 20             # letter label inside the pickup
POWERUP_SHIELD_RING_GAP = 8        # px between hull edge and the shield ring

# Explosion particles & screen shake (engagement F5): destruction looks and
# feels like destruction. Burst size scales with the destroyed body's radius;
# shake offsets the draw origin only (never entity positions) and decays
# exponentially with the clamped dt.
PARTICLES_PER_RADIUS = 0.5         # burst count = radius × intensity × this
PARTICLE_LIFETIME_SECONDS = 0.6
PARTICLE_RADIUS = 3                # spark size at birth, shrinking with life
PARTICLE_MIN_SPEED = 40            # px/s debris speed band, before intensity
PARTICLE_MAX_SPEED = 160
PLAYER_DEATH_BURST_INTENSITY = 4.0  # the ship's death bursts harder than rocks
SHAKE_DECAY = 0.001                # magnitude retained after one second
SHAKE_STOP_EPSILON = 0.1           # below this the shake snaps fully still
SHAKE_MAX_MAGNITUDE = 20           # px cap so stacked kicks stay sane
SHAKE_PLAYER_DEATH = 14.0          # px — losing a life rocks the screen
SHAKE_LARGE_ASTEROID = 6.0         # px — a large rock's death, scaled by size
