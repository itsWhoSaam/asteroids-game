/**
 * Every tunable from constants.py, mirrored verbatim — this file is the
 * web build's single source of truth for numbers. The table-pinning tests
 * (shared/constants.test.ts) hardcode the Python literals and fail the
 * moment a value drifts; port with constants.py open, never from memory.
 *
 * Keys keep the Python names (snake_case inside tables, SCREAMING_SNAKE
 * scalars) so the pinning tests read line-for-line against the source.
 */

export type UpgradeName = "nanoblade" | "fire_rate" | "income" | "drone";
export type BoughtPowerUpName = "gold_rush" | "nuke" | "overdrive" | "chrono";
export type PowerUpKind = "shield" | "rapid" | "triple";

export const SCREEN_WIDTH = 1280;
export const SCREEN_HEIGHT = 720;
export const PLAYER_RADIUS = 20;
export const LINE_WIDTH = 2;
export const PLAYER_TURN_SPEED = 300;
export const PLAYER_SPEED = 200;

export const ASTEROID_MIN_RADIUS = 20;
export const ASTEROID_KINDS = 3;
export const ASTEROID_SPAWN_RATE_SECONDS = 0.8;
export const ASTEROID_MAX_RADIUS = ASTEROID_MIN_RADIUS * ASTEROID_KINDS;

export const SHOT_RADIUS = 5;
export const PLAYER_SHOOT_SPEED = 500;

export const PLAYER_SHOOT_COOLDOWN_SECONDS = 0.3;

// Upper bound on a single frame's delta: absorbs stalls (alt-tab, window
// drag) so entities never move far enough to tunnel through a collision.
export const MAX_DT = 0.1;

// Scoring by size tier (engagement F1): smaller rocks are worth more.
export const SCORE_LARGE = 20;
export const SCORE_MEDIUM = 50;
export const SCORE_SMALL = 100;

// Lives & respawn (engagement F2): a hit costs a life, not the process.
export const PLAYER_START_LIVES = 3;
export const PLAYER_INVULNERABILITY_SECONDS = 2.0;
export const PLAYER_BLINK_HZ = 4; // the grace-window blink toggles at this rate

// Game-over overlay (engagement F2), centered on the screen.
export const GAME_OVER_FONT_SIZE = 48;
export const GAME_OVER_LINE_STEP = 60;

// Wave progression (engagement F3): clearing the field starts the next wave,
// tightening the spawn cadence and shifting the asteroid speed band up. The
// wave-1 bases are the 0.8s cadence and 40–100 px/s band the field used to
// hardcode inline.
export const WAVE_SPAWN_DECAY = 0.9; // spawn interval multiplier per wave
export const WAVE_SPAWN_INTERVAL_FLOOR = 0.3; // seconds — waves never spawn faster than this
export const ASTEROID_SPEED_MIN = 40; // wave-1 minimum asteroid speed (px/s)
export const ASTEROID_SPEED_MAX = 100; // wave-1 maximum asteroid speed (px/s)
export const WAVE_SPEED_MIN_STEP = 10; // minimum-speed increase per wave
export const WAVE_SPEED_MAX_STEP = 15; // maximum-speed increase per wave
export const WAVE_BANNER_SECONDS = 2.0; // WAVE n banner flash duration

// HUD text (engagement F1), top-left corner.
export const HUD_FONT_SIZE = 28;
export const HUD_MARGIN = 12;
export const HUD_LINE_STEP = 34;

// --- Spider-Verse palette (visual V1) --------------------------------------
// The single place color lives: every entity draw, screen fill, and the HUD
// text constant resolve through this table. Swatches are the spec's tunable
// "Miles-mode v1" identity.

export type RGB = readonly [r: number, g: number, b: number];

export type PaletteKey =
  | "paper"
  | "ship"
  | "fringe_r"
  | "fringe_c"
  | "asteroid_l"
  | "asteroid_m"
  | "asteroid_s"
  | "shot"
  | "powerup_shield"
  | "powerup_rapid"
  | "powerup_triple"
  | "spark"
  | "hud_ink"
  | "hud_panel"
  | "banner";

export const PALETTE: Record<PaletteKey, RGB> = {
  paper: [23, 18, 58], // deep-indigo void behind everything
  ship: [62, 230, 240], // cyan hull (also the shield's hue family)
  fringe_r: [255, 51, 85], // chromatic-aberration pair (outline pass V2)
  fringe_c: [47, 212, 255],
  asteroid_l: [180, 77, 255], // one hue per rock size tier
  asteroid_m: [255, 45, 149],
  asteroid_s: [255, 107, 213],
  shot: [255, 233, 74],
  powerup_shield: [62, 230, 240], // effect identity colors (F4)
  powerup_rapid: [255, 154, 62],
  powerup_triple: [255, 78, 205],
  spark: [255, 210, 63], // warm comic debris (F5)
  hud_ink: [255, 247, 230], // warm white HUD text
  hud_panel: [255, 210, 63], // yellow panels (HUD restyle, later visual PR)
  banner: [255, 210, 63],
};

export const HUD_COLOR = PALETTE.hud_ink;

// --- Idle economy core ---------------------------------------------------
// All balance numbers here are playtest starting values from the idle spec;
// none is structural. The shop turns them into purchasable controls.

// Chip damage per click. The Nanoblade upgrade multiplies this in the shop;
// the economy core wires it through with no multiplier yet.
export const CLICK_DAMAGE_BASE = 1.0;

// Chip health per size tier (tier = radius / ASTEROID_MIN_RADIUS): a small
// rock absorbs one tier's worth (~3 base clicks), a large three tiers'
// (~9). Crossing the threshold dies through the normal split() path; shots
// bypass chips entirely and keep their instant-kill split().
export const CHIP_HEALTH_PER_TIER = 3.0;

// Upgrade cost curves: cost(level) = base * growth ** level. Exponential on
// purpose — prices must always outpace linear income so the shop always has
// a next goal.
export const UPGRADE_COSTS: Record<UpgradeName, readonly [base: number, growth: number]> = {
  nanoblade: [10.0, 1.75], // click damage
  fire_rate: [25.0, 1.9], // shot cooldown
  income: [50.0, 2.0], // credit multiplier
  drone: [100.0, 2.2], // idle turret count
};

// Floating '+N' credit numbers over fresh wrecks (dt-timer lifetime).
export const FLOAT_FONT_SIZE = 20;
export const FLOAT_LIFETIME_SECONDS = 1.0;
export const FLOAT_RISE_SPEED = 40.0; // px/s upward
export const FLOAT_COLOR = "yellow";

// Idle persistence: autosave cadence; quitting also saves. The offline
// payout cap reads idle_last_seen once the drones PR lands.
export const IDLE_AUTOSAVE_SECONDS = 30.0;

// --- Upgrade shop ---------------------------------------------------------
// Multiplier steps applied per purchased level; the cost curves themselves
// live in UPGRADE_COSTS above (the Economy owns the curve, the shop buys
// through it). Spec-table values — playtest starting points, none structural.

export const NANOBLADE_MULT_PER_LEVEL = 1.8; // click chip damage ×1.8 per Nanoblade level
export const FIRE_RATE_MULT_PER_LEVEL = 0.88; // shot cooldown ×0.88 per Fire-rate level
// The cooldown never drops below this, however many Fire-rate levels are bought.
export const PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS = 0.03;
export const INCOME_MULT_PER_LEVEL = 1.15; // credit payouts ×1.15 per Income level

// Bottom shop panel: one strip across the screen width, below the play
// field — clear of the top-left score HUD (F1) and the centered game-over
// overlay (F2).
export const SHOP_FONT_SIZE = 18;
export const SHOP_PANEL_HEIGHT = 64;
export const SHOP_CELL_PADDING = 10;
export const SHOP_LINE_STEP = 22;
export const SHOP_PANEL_BG: RGB = [16, 16, 28];
export const SHOP_PANEL_BORDER: RGB = [70, 70, 90];
export const SHOP_DIM_COLOR: RGB = [100, 100, 100]; // an upgrade the ledger can't pay for yet
export const SHOP_BRIGHT_COLOR: RGB = [255, 230, 120]; // affordable — the next purchase glows

// Shop upgrade definitions (shop.py's UPGRADES tuples): identity, key
// binding, and panel copy. Python binds pygame.K_1..K_4 (ASCII 49–52); the
// web build binds the digit characters — same keys the player presses.
export interface UpgradeDef {
  name: UpgradeName;
  title: string;
  key: string;
  effect: string;
}

export const UPGRADE_DEFS: readonly UpgradeDef[] = [
  { name: "nanoblade", title: "Nanoblade", key: "1", effect: "click damage ×1.8/lvl" },
  { name: "fire_rate", title: "Fire-rate", key: "2", effect: "shot cooldown ×0.88/lvl" },
  { name: "income", title: "Income", key: "3", effect: "credit payouts ×1.15/lvl" },
  { name: "drone", title: "Drones", key: "4", effect: "auto-turret per level" },
];

// --- Idle drones & offline earnings ---------------------------------------
// One auto-turret per Drones level. Turrets fire REAL shots into the
// existing shots pipeline, so drone kills flow through the same collision
// sweep and the same mint path as player shots — one destruction pipeline
// pays every source.

export const DRONE_FIRE_INTERVAL_S = 1.5; // per-turret cadence: one instant-kill shot
export const DRONE_SHOT_SPEED = 500; // px/s — matches the player's shot feel
export const DRONE_ORBIT_RADIUS = 36; // px from ship center; markers clear PLAYER_RADIUS
export const DRONE_ORBIT_SPEED = 72.0; // deg/s — one lap every 5 s, purely visual
export const DRONE_MARKER_RADIUS = 5; // px — the small distinct turret marker
export const DRONE_MARKER_COLOR: RGB = [90, 220, 200]; // teal — distinct from ship, shots, floats

// Offline payout estimate: a drone shot kills a rock of unknown size, so the
// grant prices the medium tier per shot instead of reading the live table.
export const DRONE_CREDITS_PER_SHOT = 50.0;

// Time away still pays, per the spec's balance table: capped at 8 hours and
// paid at half rate. Disabled in multiplayer rooms — it prices wall-clock
// absence, which is abusive over a network.
export const OFFLINE_CAP_SECONDS = 8 * 3600;
export const OFFLINE_RATE = 0.5;

// The one-time 'Offline earnings +N' HUD line fades out over this long.
export const OFFLINE_BANNER_SECONDS = 4.0;

// --- Economy-activated insane powerups (idle release) ----------------------
// Bought activations, not drops: keys 7–0 fire them, credits price them,
// and each use re-arms its duration from this table. The table mirrors
// the F4 drop-pickup tables' shape — data-driven, one entry per effect.
// Python binds pygame.K_7/K_8/K_9/K_0 (ASCII 55/56/57/48); the web build
// binds the digit characters. All numbers are playtest starting values.

// One entry per powerup: base price in credits, activation key, duration
// in seconds (0.0 = instant, like the nuke), and the panel descriptor.
export interface PowerUpDef {
  title: string;
  cost: number;
  key: string;
  duration: number;
  desc: string;
}

export const POWERUPS: Record<BoughtPowerUpName, PowerUpDef> = {
  gold_rush: { title: "Gold Rush", cost: 400, key: "7", duration: 15.0, desc: "credit income ×5" },
  nuke: { title: "Nuke", cost: 1000, key: "8", duration: 0.0, desc: "clear the field, full payout" },
  overdrive: { title: "Overdrive", cost: 250, key: "9", duration: 10.0, desc: "click damage ×10" },
  chrono: { title: "Chrono", cost: 300, key: "0", duration: 8.0, desc: "asteroid speed ×0.5" },
};

// price(name) = entry cost × POWERUP_PER_USE_PRICE_GROWTH ** uses — each
// activation raises that powerup's own next price, so a nuke stays a
// decision instead of a rhythm button.
export const POWERUP_PER_USE_PRICE_GROWTH = 1.25;

// Magnitudes, one named constant each: gold rush multiplies every mint
// through the income seam (stacking with the Income upgrade); overdrive
// multiplies click chip damage only — shots stay instant-kill; chrono
// halves asteroid velocity while active and the exact factor divides out
// at expiry so base speed is restored fully.
export const POWERUP_GOLD_RUSH_MULT = 5.0;
export const POWERUP_OVERDRIVE_MULT = 10.0;
export const POWERUP_CHRONO_SLOW = 0.5;

// Panel row 2 + indicator colors. constants.py assigns POWERUP_ACTIVE_COLOR
// twice — (120, 255, 180) in the F-powerup block, then (255, 160, 40) in
// this block; the second assignment wins at import time, so that is the
// effective value pinned here.
export const POWERUP_COLOR: RGB = [170, 120, 255]; // violet — reads apart from upgrades
export const POWERUP_ACTIVE_COLOR: RGB = [255, 160, 40]; // orange while an effect's clock runs

// Power-ups (engagement F4): a destroyed non-small rock can drop a timed
// pickup. Effects are data-driven — every duration and magnitude lives in
// these tables (keys match PowerUpKind) so retunes never touch gameplay code.
export const POWERUP_DROP_CHANCE = 0.15; // chance a destroyed non-small rock drops one
export const POWERUP_DURATION_S: Record<PowerUpKind, number> = {
  shield: 8.0,
  rapid: 8.0,
  triple: 8.0,
};
export const POWERUP_RAPID_COOLDOWN_MULT = 0.4; // RAPID multiplies the shoot cooldown
export const POWERUP_TRIPLE_SPREAD = 20.0; // degrees between the three TRIPLE shots
export const POWERUP_SHIELD_HITS = 1; // hits one shield absorbs
export const POWERUP_RADIUS = 14;
export const POWERUP_DRIFT_SPEED = 30; // px/s — pickups drift, they don't sit still
export const POWERUP_FONT_SIZE = 20; // letter label inside the pickup
export const POWERUP_SHIELD_RING_GAP = 8; // px between hull edge and the shield ring

// Explosion particles & screen shake (engagement F5): destruction looks and
// feels like destruction. Burst size scales with the destroyed body's radius;
// shake offsets the draw origin only (never entity positions) and decays
// exponentially with the clamped dt.
export const PARTICLES_PER_RADIUS = 0.5; // burst count = radius × intensity × this
export const PARTICLE_LIFETIME_SECONDS = 0.6;
export const PARTICLE_RADIUS = 3; // spark size at birth, shrinking with life
export const PARTICLE_SPAWN_POP = 0.6; // birth-size boost fraction (visual V2 size-pop)
export const PARTICLE_MIN_SPEED = 40; // px/s debris speed band, before intensity
export const PARTICLE_MAX_SPEED = 160;
export const PLAYER_DEATH_BURST_INTENSITY = 4.0; // the ship's death bursts harder than rocks
export const SHAKE_DECAY = 0.001; // magnitude retained after one second
export const SHAKE_STOP_EPSILON = 0.1; // below this the shake snaps fully still
export const SHAKE_MAX_MAGNITUDE = 20; // px cap so stacked kicks stay sane
export const SHAKE_PLAYER_DEATH = 14.0; // px — losing a life rocks the screen
export const SHAKE_LARGE_ASTEROID = 6.0; // px — a large rock's death, scaled by size

// Sound & mute (engagement F6): every SFX is synthesized at startup — no
// binary assets, no new runtime dependencies. Builders render into the
// mixer's init format (stereo signed 16-bit at CD rate); every duration
// and pitch lives in this block so retunes never touch the sound logic.
export const SFX_SAMPLE_RATE = 44100;
export const SFX_FORMAT = -16; // signed 16-bit samples
export const SFX_CHANNELS = 2; // stereo
export const SFX_NOISE_SEED = 7; // fixed: explosion buffers are deterministic

export const SFX_SHOOT = "shoot";
export const SFX_EXPLOSION_SMALL = "explosion_small";
export const SFX_EXPLOSION_MEDIUM = "explosion_medium";
export const SFX_EXPLOSION_LARGE = "explosion_large";
export const SFX_POWERUP = "powerup";
export const SFX_GAME_OVER = "game_over";

// Shoot: a short descending blip (Hz start → end, peak amplitude).
export const SFX_SHOOT_DURATION = 0.1;
export const SFX_SHOOT_SWEEP: readonly [number, number] = [900.0, 300.0];
export const SFX_SHOOT_VOLUME = 0.5;

// Explosions: noise over a low thump, pitched and sized per asteroid tier —
// small rocks crack bright and fast, large ones rumble longer.
export const SFX_EXPLOSION_VOLUME = 0.6;
export interface SfxTier {
  duration: number;
  thump_hz: number;
  brightness: number;
}

export const SFX_EXPLOSION_TIERS: Record<"small" | "medium" | "large", SfxTier> = {
  small: { duration: 0.18, thump_hz: 220.0, brightness: 0.8 },
  medium: { duration: 0.3, thump_hz: 120.0, brightness: 0.6 },
  large: { duration: 0.45, thump_hz: 70.0, brightness: 0.5 },
};

// Power-up: a rising chirp.
export const SFX_POWERUP_DURATION = 0.22;
export const SFX_POWERUP_SWEEP: readonly [number, number] = [300.0, 900.0];
export const SFX_POWERUP_VOLUME = 0.5;

// Game over: a long descending tone, the run winding down.
export const SFX_GAME_OVER_DURATION = 0.8;
export const SFX_GAME_OVER_SWEEP: readonly [number, number] = [440.0, 90.0];
export const SFX_GAME_OVER_VOLUME = 0.6;

// --- Newtonian ship physics (physics overhaul) ------------------------------
// Mirrored from constants.py's block of the same name — the parity test
// (shared/physics.test.ts) reads the Python literals and fails the moment
// these values drift. The ship is a body: W accelerates along the nose, S
// retro-thrusts at a fraction of it, and the velocity they build persists
// between frames — coasting under light linear damping instead of stopping
// dead. PLAYER_MAX_SPEED keeps the anti-tunnel arithmetic honest: the worst
// clamped frame moves 360 px/s * MAX_DT (0.1 s) = 36 px, inside the 40 px
// minimum contact overlap, so overlap cannot be jumped over and no
// swept-collision machinery is needed.
export const PLAYER_THRUST_ACCEL = 600.0; // px/s^2 along the nose while W is held
export const PLAYER_RETRO_FACTOR = 0.6; // S thrusts opposite the nose at this fraction
export const PLAYER_MAX_SPEED = 360.0; // px/s ceiling — thrust and impulse all clamp
export const PLAYER_LINEAR_DAMPING = 0.5; // 1/s exponential drag (speed ~halves every 1.4 s)

// Dash retune, mirrored for parity though the web sim carries no dash: the
// impulse composes with carried momentum instead of being the ship's only
// velocity. constants.py rebinds this name by append — the 340.0 below the
// original 420.0 is the value every import reads.
export const DASH_IMPULSE = 340.0;

// --- Impulse collision response (physics overhaul) --------------------------
// Every body on the field carries a mass: rocks scale with area —
// (radius / ASTEROID_MIN_RADIUS)^2, so a large rock outweighs a small one
// nine to one — and the ship is a fixed small body (one small rock's worth
// of inertia). Contacts resolve along the center-to-center normal through
// the pure sim.resolveContact: an impulse proportional to the closing
// speed, then de-penetration proportional to inverse mass. All numbers are
// playtest starting values; none is structural.
export const COLLISION_RESTITUTION = 0.85; // bounce share kept along the normal (1 = elastic)
export const PLAYER_MASS = 1.0; // the ship weighs one small rock — hits move it
