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