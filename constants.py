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
