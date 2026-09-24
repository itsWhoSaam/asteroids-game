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
