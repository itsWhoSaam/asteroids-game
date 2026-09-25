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

# --- Comic HUD panels (visual V5) -------------------------------------------
# The score/lives/wave HUD, the game-over overlay lines, and the wave banner
# sit on pre-rendered yellow halftone panels with black ink borders. Padding
# is shared by all three surfaces; the banner's per-letter tilt and the fade
# quantization are banner-only.

PANEL_PAD_X = 14                   # px of yellow between border and text, each side
PANEL_PAD_Y = 8                    # px of yellow between border and text, top/bottom

# The banner fade renders at BANNER_ALPHA_STEPS discrete alpha bands (baked
# into the glyph colors through the shared cache), so the number of cached
# letter surfaces is bounded — a cache entry per (letter, band, tilt), never
# per frame. Eight bands over a 2s flash read as a smooth glide.
BANNER_ALPHA_STEPS = 8

# Slight per-letter rotation (degrees) — comic hand-lettering, alternating
# sign down the line. Locked small: this is a tilt, not a tumble.
WAVE_BANNER_TILT_DEGREES = 4.0

# --- Spider-Verse palette (visual V1) --------------------------------------
# The single place color lives: every entity draw, screen fill, and the HUD
# text constant resolve through this table, and the pixel tests assert
# against these same entries — a regrade is a one-line diff per swatch.
# Swatches are the spec's tunable "Miles-mode v1" identity.
PALETTE = {
    "paper": (23, 18, 58),         # deep-indigo void behind everything
    "halftone": (62, 51, 140),     # print-screen dots over the paper (V3)
    "action_line": (40, 32, 94),   # faint radial speed lines (V3)
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
    "powerup_mystery": (170, 120, 255),  # violet — the ? gamble (insanity chaos)
    "spark": (255, 210, 63),       # warm comic debris (F5)
    "hud_ink": (255, 247, 230),    # warm white HUD text
    "hud_panel": (255, 210, 63),   # yellow panels (HUD restyle, V5)
    "hud_panel_dot": (222, 176, 40),  # darker mustard halftone dots on the panels (V5)
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
    # Insanity chaos: the new timed effects join the same table — the
    # runtime source of every duration. BOMB and DISARM are instant (they
    # fire and strip in activate_powerup, never arming a clock) and MYSTERY
    # resolves on collect, so none of the three has a duration entry.
    "pierce": 8.0,
    "homing": 8.0,
    "reverse": 6.0,  # = CURSE_REVERSE_S below — the readable alias
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
PARTICLE_SPAWN_POP = 0.6           # birth-size boost fraction (visual V2 size-pop)
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

# --- Insanity chaos: mystery & curse pickups --------------------------------
# All numbers here are playtest starting values from the insanity spec; none
# is structural. Every tunable lives in this one block — tuning happens
# here, never in gameplay code.

# The mystery gamble: 40% of paid drops are the '?' wildcard (known buffs
# get rarer), and a ? open is a 25% sting — a curse (equal odds) instead of
# a buff. Curses never drop directly: the reveal is the gamble.
MYSTERY_DROP_CHANCE = 0.40
MYSTERY_CURSE_CHANCE = 0.25
# The controls answer backwards while the reverse curse runs. The duration
# table above is the runtime source (activate_powerup reads it like every
# other effect); this is the readable alias the curse logic and tests use.
CURSE_REVERSE_S = POWERUP_DURATION_S["reverse"]

# Homing shots steer toward the nearest asteroid at up to this heading
# change per second — speed preserved, so the buff bends bullets, not
# accelerates them.
HOMING_TURN_RATE_S = 360.0

# The bomb pickup's field clear rocks the screen: harder than one large
# rock, softer than losing a life (SHAKE_PLAYER_DEATH).
SHAKE_BOMB = 12.0

# The ? pickup's identity hue: violet, keyed through the palette (visual V1)
# like every other color site.
MYSTERY_COLOR = PALETTE["powerup_mystery"]

# Curse reveal: a dissonant sting — two tones a rubbed half-step apart,
# sinking together. The sound that makes the next ? hesitate.
SFX_CURSE = "curse"
SFX_CURSE_DURATION = 0.45
SFX_CURSE_TONES = (392.0, 415.3)  # G4 against a quarter-flat G#4
SFX_CURSE_VOLUME = 0.55
# --- Master volume (UX wave) -------------------------------------------------
# '[' / ']' step the master volume between 0 and 100 in 10% steps; every SFX
# scales by the level at playback (the per-cue volumes above stay baked into
# the buffers). Mute still suppresses playback outright and never overwrites
# the stored level. The level persists in game_save.json through the save
# loader's read-modify-write merge.
VOLUME_MIN = 0
VOLUME_MAX = 100
VOLUME_STEP = 10                   # percent per '[' / ']' press
VOLUME_DEFAULT = 100               # fresh installs and corrupt saves land here
HUD_TAG_GAP = 10                   # px between the VOL and MUTED tags top-right

# --- Pause overlay (Tier 1) -------------------------------------------------
# P or Esc freezes a live run: a paused flag gates every world update and a
# dim sheet plus the PAUSED prompt render over the frozen frame. Pause is
# run state — never persisted, and every restart unpauses. The dim blits
# uniform surface alpha (set_alpha, the WaveBanner fade precedent) because
# per-pixel alpha breaks the headless dummy drivers.
PAUSE_OVERLAY_DIM_COLOR = (12, 10, 34)  # deep-void family, over the paper
PAUSE_OVERLAY_DIM_ALPHA = 160           # 0–255 dim strength over the frame

# --- Extra SFX (UX wave) ------------------------------------------------------
# Three more cues out of the same synth block: the drones' pew (a fleet fires
# on a cadence, so it sits under the player's shot), the shop's denied buzz
# for an unaffordable purchase, and the wave-clear arpeggio. Every one scales
# by master volume and honors mute at playback, exactly like the cues above.
SFX_DRONE_FIRE = "drone_fire"
SFX_DENIED = "denied"
SFX_WAVE_CLEAR = "wave_clear"

# Drone fire: a shorter, brighter pew than the player's own shot.
SFX_DRONE_FIRE_DURATION = 0.07
SFX_DRONE_FIRE_SWEEP = (1600.0, 800.0)
SFX_DRONE_FIRE_VOLUME = 0.35

# Denied: two low square thuds with a gap — the "can't afford it" buzz.
SFX_DENIED_HZ = 130.0
SFX_DENIED_THUD_S = 0.07
SFX_DENIED_GAP_S = 0.04
SFX_DENIED_VOLUME = 0.4

# Wave clear: a rising major arpeggio (C5 E5 G5 C6), one humped note per slot.
SFX_WAVE_CLEAR_NOTE_S = 0.09
SFX_WAVE_CLEAR_ARPEGGIO = (523.25, 659.25, 783.99, 1046.50)
SFX_WAVE_CLEAR_VOLUME = 0.45

# --- Wave milestone rewards (Tier 1) -----------------------------------------
# Every MILESTONE_WAVE_INTERVAL-th cleared wave grants the ship a shield
# charge plus a flat credit bonus to the idle ledger, announced in the wave
# banner. The charge is kept until spent — no duration clock, unlike a
# drop-shield's timed window. The bonus is flat rather than income-scaled so
# the banner announces the exact number the ledger receives.
MILESTONE_WAVE_INTERVAL = 5
MILESTONE_SHIELD_CHARGES = 1
MILESTONE_CREDIT_BONUS = 500.0

# --- Help overlay (Tier 1) ---------------------------------------------------
# H toggles a keybind-list overlay over dimmed play; H again dismisses it. The
# dim reuses the pause overlay's sheet (PAUSE_OVERLAY_DIM_* above) — one dim
# treatment, two overlays. The rows are data: hud.help_keymap() renders shop
# and powerup entries straight from the tables the handlers read, and the test
# suite pins every listed key to a live handler, so the list cannot drift
# from what the game actually answers. Help dims, it never freezes — pause is
# the freeze, and the two overlays stack when both are open.
HELP_FONT_SIZE = 24               # dense list font, between HUD and game-over
HELP_LINE_STEP = 30               # px between help rows
HELP_TITLE_STEP = 56              # px between the title and the first row

# --- Low-lives warning (UX wave) ---------------------------------------------
# At exactly LOW_LIVES_THRESHOLD lives the HUD lives line pulses in size and a
# stepped vignette darkens the screen edges until the run leaves the gate —
# respawn, game over, or restart. Both effects keep the headless contract: the
# pulse re-renders the line at oscillating sizes (the size-fade precedent),
# and the vignette blits uniform surface-alpha strips (the pause-dim
# precedent) — never per-pixel alpha.
LOW_LIVES_THRESHOLD = 1              # the gate: exactly this many lives left
LOW_LIVES_PULSE_SECONDS = 0.9        # s per full size oscillation
LOW_LIVES_PULSE_AMPLITUDE = 1.2      # peak size factor over the resting line
LOW_LIVES_VIGNETTE_COLOR = PALETTE["fringe_r"]  # danger red, the fringe family
LOW_LIVES_VIGNETTE_BANDS = 3         # stepped frames from the edge inward
LOW_LIVES_VIGNETTE_BAND_WIDTH = 14   # px per band step inward
LOW_LIVES_VIGNETTE_MAX_ALPHA = 80    # outermost band strength, 0–255
LOW_LIVES_VIGNETTE_ALPHA_STEP = 28   # fade per band inward

# --- Distinct score popups (Tier 2) ------------------------------------------
# Points and credits both float over a wreck on the FloatingText dt-timer
# template, and main.popup_style resolves each kind's look: a shot kill's
# points award announces '+N pts' in the palette's warm white, while credits
# keep their yellow '+N'. The points popup spawns a head above the credit
# float paid on the same frame by the destruction diff, so the pair stacks
# instead of overlapping. Display only — neither kind touches economy math.
SCORE_COLOR = PALETTE["hud_ink"]  # warm white — reads apart from yellow credits
SCORE_POPUP_OFFSET_Y = 24.0       # px head start above the credit float's line

# --- Chip-damage cracks (Tier 2) ---------------------------------------------
# Idle-clicked rocks wear their damage: chip damage maps to a 0-3 crack stage
# through fractions of the same threshold take_chip kills by, and the draw
# renders an ink crack web that deepens stage by stage (comicfx.draw_cracks).
# Fractions, not absolute damage, so every size tier cracks on the same cue.
# Purely visual — no economy path changes, the destruction diff reads the
# same split() it always did.

# The damage fraction that deepens the web one stage, in draw order: a rock
# at a quarter of its chip threshold shows the first hairline pair, and the
# last stage lands a click or two before the split. Crossing is inclusive
# (>=): a rock AT the mark shows the next stage.
CHIP_CRACK_FRACTIONS = (0.25, 0.50, 0.75)

# --- Run stats + end-of-run summary (run-stats PR) ---------------------------
# Per-run counters — shots fired/hit, rocks destroyed by size tier, waves
# survived, credits earned split idle-vs-click — reported by a summary block
# under the game-over prompt. Run-scoped only: never persisted, so no save
# key and nothing for the restart hooks to preserve. The block renders as
# caption panels in the V5 family, seated below the game-over overlay's
# worst case (three lines) and above the shop panel's bottom edge.
STATS_FONT_SIZE = 24        # dense summary rows — the help list's size
STATS_LINE_STEP = 30        # px between summary rows
STATS_BLOCK_GAP = 36        # px between the game-over block and the summary
