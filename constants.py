import pygame

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

# --- Spider-Verse palette (visual V1) --------------------------------------
# The single place color lives: every entity draw, screen fill, and the HUD
# text constant resolve through this table, and the pixel tests assert
# against these same entries — a regrade is a one-line diff per swatch.
# Swatches are the spec's tunable "Miles-mode v1" identity.
PALETTE = {
    "paper": (23, 18, 58),         # deep-indigo void behind everything
    "ship": (62, 230, 240),        # cyan hull (also the shield's hue family)
    "fringe_r": (255, 51, 85),     # chromatic-aberration pair (outline pass V2)
    "fringe_c": (47, 212, 255),
    "asteroid_l": (180, 77, 255),  # one hue per rock size tier
    "asteroid_m": (255, 45, 149),
    "asteroid_s": (255, 107, 213),
    "shot": (255, 233, 74),
    "powerup_shield": (62, 230, 240),  # effect identity colors (F4)
    "powerup_rapid": (255, 154, 62),
    "powerup_triple": (255, 78, 205),
    "spark": (255, 210, 63),       # warm comic debris (F5)
    "hud_ink": (255, 247, 230),    # warm white HUD text
    "hud_panel": (255, 210, 63),   # yellow panels (HUD restyle, later visual PR)
    "banner": (255, 210, 63),
}

HUD_COLOR = PALETTE["hud_ink"]

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

# --- Economy-activated insane powerups (idle release) ----------------------
# Bought activations, not drops: keys 7–0 fire them, credits price them,
# and each use re-arms its duration from this table. The table mirrors
# sibling F4's drop-pickup constants shape — data-driven, one dict per
# effect — but extends the pattern for purchases: F4's POWERUP_* drop
# tables are theirs and stay untouched. All numbers are playtest starting
# values; none is structural.

# One entry per powerup: base price in credits, activation key, duration
# in seconds (0.0 = instant, like the nuke), and the panel descriptor.
POWERUPS = {
    "gold_rush": {"title": "Gold Rush", "cost": 400, "key": pygame.K_7, "duration": 15.0, "desc": "credit income ×5"},
    "nuke": {"title": "Nuke", "cost": 1000, "key": pygame.K_8, "duration": 0.0, "desc": "clear the field, full payout"},
    "overdrive": {"title": "Overdrive", "cost": 250, "key": pygame.K_9, "duration": 10.0, "desc": "click damage ×10"},
    "chrono": {"title": "Chrono", "cost": 300, "key": pygame.K_0, "duration": 8.0, "desc": "asteroid speed ×0.5"},
}

# price(name) = entry cost × POWERUP_PER_USE_PRICE_GROWTH ** uses — each
# activation raises that powerup's own next price, so a nuke stays a
# decision instead of a rhythm button.
POWERUP_PER_USE_PRICE_GROWTH = 1.25

# A running timed effect glows green in the HUD indicator with its
# seconds remaining; activation labels float in the same color.
POWERUP_ACTIVE_COLOR = (120, 255, 180)

# Magnitudes, one named constant each: gold rush multiplies every mint
# through the income seam (stacking with the Income upgrade); overdrive
# multiplies click chip damage only — shots stay instant-kill; chrono
# halves asteroid velocity while active and the exact factor divides out
# at expiry so base speed is restored fully.
POWERUP_GOLD_RUSH_MULT = 5.0
POWERUP_OVERDRIVE_MULT = 10.0
POWERUP_CHRONO_SLOW = 0.5

# Panel row 2 + indicator colors: the powerup strip renders under the
# upgrade cells inside the same panel; active effects also light the
# small HUD indicator line with their remaining seconds.
POWERUP_COLOR = (170, 120, 255)        # violet — reads apart from upgrades
POWERUP_ACTIVE_COLOR = (255, 160, 40)  # orange while an effect's clock runs

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

# Sound & mute (engagement F6): every SFX is synthesized at startup from
# stdlib array/math envelopes — no binary assets, no numpy, no new runtime
# dependencies. Builders render into the mixer's init format (stereo signed
# 16-bit at CD rate); every duration and pitch lives in this block so the
# idle-economy follow-up can retune without touching sound.py's logic.
SFX_SAMPLE_RATE = 44100
SFX_FORMAT = -16                   # signed 16-bit samples
SFX_CHANNELS = 2                   # stereo
SFX_NOISE_SEED = 7                 # fixed: explosion buffers are deterministic

SFX_SHOOT = "shoot"
SFX_EXPLOSION_SMALL = "explosion_small"
SFX_EXPLOSION_MEDIUM = "explosion_medium"
SFX_EXPLOSION_LARGE = "explosion_large"
SFX_POWERUP = "powerup"
SFX_GAME_OVER = "game_over"

# Shoot: a short descending blip (Hz start → end, peak amplitude).
SFX_SHOOT_DURATION = 0.10
SFX_SHOOT_SWEEP = (900.0, 300.0)
SFX_SHOOT_VOLUME = 0.5

# Explosions: noise over a low thump, pitched and sized per asteroid tier —
# small rocks crack bright and fast, large ones rumble longer.
SFX_EXPLOSION_VOLUME = 0.6
SFX_EXPLOSION_TIERS = {
    "small":  {"duration": 0.18, "thump_hz": 220.0, "brightness": 0.8},
    "medium": {"duration": 0.30, "thump_hz": 120.0, "brightness": 0.6},
    "large":  {"duration": 0.45, "thump_hz": 70.0,  "brightness": 0.5},
}

# Power-up: a rising chirp.
SFX_POWERUP_DURATION = 0.22
SFX_POWERUP_SWEEP = (300.0, 900.0)
SFX_POWERUP_VOLUME = 0.5

# Game over: a long descending tone, the run winding down.
SFX_GAME_OVER_DURATION = 0.8
SFX_GAME_OVER_SWEEP = (440.0, 90.0)
SFX_GAME_OVER_VOLUME = 0.6

# --- Insanity core: combo, hit-stop, dash ---------------------------------
# All numbers here are playtest starting values from the insanity spec; none
# is structural. Every tunable lives in this one block — tuning happens
# here, never in gameplay code.

# Combo multiplier (score feature, not a currency feature): every rock
# destroyed by player-or-drone fire within the window extends the chain,
# and the kill's points pay through combo_multiplier(chain). Credits mint
# exactly as before — the multiplier never touches the ledger.
COMBO_WINDOW_SECONDS = 3.0        # chain lifetime after each kill
COMBO_STEP = 0.25                 # multiplier added per chain link (x2 at chain 5)
COMBO_CAP = 5.0                   # multiplier ceiling
COMBO_MILESTONES = (5, 10, 20, 50)  # chains that log + chirp once per run
COMBO_BREAK_MIN_CHAIN = 3         # breaking a shorter chain is silent, unlogged
COMBO_COLOR = (255, 191, 0)       # amber readout under the wave slot

# Hit-stop: every destruction holds the whole simulation for a beat. The
# freeze itself and the shake decay tick on real dt so the pause always ends.
HIT_STOP_BASE_S = 0.05            # one kill in a frame
HIT_STOP_MULTI_S = 0.09           # several dying inside one frame
# The multi duration expressed in freeze(scale=...) units, so one formula
# prices every request and the two named durations stay the source of truth.
HIT_STOP_MULTI_SCALE = HIT_STOP_MULTI_S / HIT_STOP_BASE_S

# Dash: a SHIFT impulse along the nose. I-frames ride the respawn grace via
# max() — never shorter — and dashing breaks the combo: the panic button
# has a price. The impulse bleeds off over DASH_DECAY_S, so the ship glides
# then handles normally.
DASH_IMPULSE = 420.0              # px/s added to velocity along the nose
DASH_IFRAME_S = 0.25              # invulnerability granted
DASH_COOLDOWN_S = 2.0             # between dashes
DASH_DECAY_S = 0.4                # the impulse bleeds off over this long
DASH_DECAY = 0.001                # impulse fraction retained after one second
DASH_COOLING_COLOR = (110, 110, 110)  # the cooling slot, dim against HUD_COLOR

# HUD rows the insanity slots claim: the combo readout sits directly under
# the wave slot, the dash slot below it, and the credits line (idle core)
# drops beneath both so nothing overlaps.
HUD_CREDITS_ROW = 5

# Dash: a crisp whoosh — bright noise over a fast falling chirp, swelling
# and gone in under a fifth of a second. Recipe follows the F6 builders.
SFX_DASH = "dash"
SFX_DASH_DURATION = 0.18
SFX_DASH_SWEEP = (1400.0, 180.0)
SFX_DASH_BRIGHTNESS = 0.7
SFX_DASH_VOLUME = 0.45

# Combo break: a descending sigh — the chain dying audibly.
SFX_COMBO_BREAK = "combo_break"
SFX_COMBO_BREAK_DURATION = 0.5
SFX_COMBO_BREAK_SWEEP = (520.0, 140.0)
SFX_COMBO_BREAK_VOLUME = 0.5

# --- Insanity threats: bosses, saucers, black holes ------------------------
# All numbers here are playtest starting values from the insanity spec; none
# is structural. Every tunable lives in this one block — tuning happens
# here, never in gameplay code.

# Boss waves: every BOSS_WAVE_INTERVAL-th wave fields one multi-hit boss
# instead of the regular field. Tier = wave // interval, capped by the
# radius table's largest tier. Bosses pay score through register_kill only
# (BOSS_POINTS × the combo multiplier) — never credits, never pickups.
BOSS_WAVE_INTERVAL = 5
BOSS_RADIUS_TIERS = {1: 4, 2: 5, 3: 6}  # × ASTEROID_MIN_RADIUS
BOSS_HP_PER_TIER = 6
BOSS_POINTS = 300
# Minion checkpoint fractions of the boss's max HP: crossing each threshold
# (70/40/15%) spawns two mediums at the boss — the fight gets harder as it
# gets safer. A fixed ladder, so every tier fields three waves.
MINION_CHECKPOINT_FRACTIONS = (0.70, 0.40, 0.15)
MINION_RADIUS_MULTIPLIER = 2  # medium asteroids, per checkpoint
SHAKE_BOSS_DEATH = 16.0       # px — the boss's death rocks the screen hard

# The boss health bar (hud.draw_boss_bar): top-center during boss waves.
BOSS_BAR_WIDTH = 480
BOSS_BAR_HEIGHT = 10
BOSS_BAR_Y = HUD_MARGIN + 6
BOSS_BAR_FILL_COLOR = PALETTE["fringe_r"]  # hostile red fill
BOSS_BAR_TRACK_COLOR = (40, 40, 60)        # dim track against the paper

# Enemy saucers: from wave 2 a jittered interval enters one from a random
# edge; kinds alternate. Big saucers cross slower and fire 3-way spreads;
# small saucers cross fast and fire aimed single shots — worth far more.
SAUCER_FIRST_WAVE = 2
SAUCER_SPAWN_INTERVAL_S = 20.0
SAUCER_SPAWN_JITTER_S = 8.0
SAUCER_RADIUS = {"big": 24, "small": 16}
SAUCER_KINDS = {
    "big":   {"fire_interval": 2.0, "spread": 3, "shot_speed": 350.0,
              "hp": 2, "points": 200, "speed": 80.0},
    "small": {"fire_interval": 1.2, "spread": 1, "shot_speed": 450.0,
              "hp": 1, "points": 1000, "speed": 140.0},
}
SAUCER_KIND_ORDER = ("big", "small")  # the alternation order
SAUCER_BOB_AMPLITUDE = 60    # px of sine bob under the horizontal cross
SAUCER_BOB_FREQUENCY = 0.5   # Hz — one full bob every two seconds
SAUCER_SPREAD_DEGREES = 20.0 # between the big saucer's three shots
SAUCER_EDGE_MARGIN = 40      # cull margin beyond is_off_screen's radius
SAUCER_SHAKE_DEATH = 8.0     # px — a saucer's death kicks the screen

# Black holes: from wave 3 a timer drops a gravity well that bends every
# trajectory. It kills nothing directly — the danger is eaten agency and
# drifted rocks. It never spawns during a boss wave.
BLACK_HOLE_FIRST_WAVE = 3
BLACK_HOLE_FIRST_DELAY_S = 15.0
BLACK_HOLE_REPEAT_DELAY_S = 22.0
BLACK_HOLE_JITTER_S = 8.0
BLACK_HOLE_LIFETIME_S = 12.0
BLACK_HOLE_WARNING_S = 2.0   # the final blink window
BLACK_HOLE_RADIUS = 26
# accel_at: inverse-falloff pull toward the hole, capped at the core. The
# min distance keeps the math finite inside the well itself.
BLACK_HOLE_STRENGTH = 4e6
BLACK_HOLE_FALLOFF = 1.5
BLACK_HOLE_MAX_ACCEL = 2000.0
BLACK_HOLE_MIN_DIST = 40.0
BLACK_HOLE_PLAYER_FACTOR = 0.5  # the ship fights the pull at half strength
BLACK_HOLE_SPAWN_MARGIN = 100   # px kept clear of every screen edge

# Saucer fire: a two-tone warble — two detuned tones beating against each
# other while the shot leaves.
SFX_SAUCER = "saucer"
SFX_SAUCER_DURATION = 0.25
SFX_SAUCER_TONES = (620.0, 780.0)
SFX_SAUCER_VOLUME = 0.4

# Boss spawn: a low double-thump — the field's weight arriving.
SFX_BOSS = "boss"
SFX_BOSS_DURATION = 0.9
SFX_BOSS_THUMP_HZ = 90.0
SFX_BOSS_VOLUME = 0.7

# Black hole: a low rumble — noise over a sinking tone, swelling slowly.
SFX_BLACKHOLE = "blackhole"
SFX_BLACKHOLE_DURATION = 1.1
SFX_BLACKHOLE_SWEEP = (110.0, 45.0)
SFX_BLACKHOLE_BRIGHTNESS = 0.35
SFX_BLACKHOLE_VOLUME = 0.5
