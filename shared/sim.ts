/**
 * The shared simulation: one authoritative world advanced by `step` at a
 * fixed dt. The Node server runs it as room authority; the browser runs the
 * same module for solo mode — there is no second implementation to drift.
 *
 * Ported 1:1 from the pygame sources: main.py's per-frame block (update →
 * drones → collision sweep → wave guard → economy tick → destruction-mint
 * diff) and the entity update methods. Presentation never leaks in here —
 * `step` returns GameEvent[] and the client maps them to particles, shake,
 * floating text, and sound. Every number comes from constants.ts, which
 * mirrors constants.py verbatim.
 *
 * Message intents (buy, click, restart) are direct function calls the host
 * makes when a ClientMsg arrives — the Python build handles those in its
 * event pump between frames, and this preserves that semantics.
 */

import {
  ASTEROID_KINDS,
  ASTEROID_MAX_RADIUS,
  ASTEROID_MIN_RADIUS,
  ASTEROID_SPEED_MAX,
  ASTEROID_SPEED_MIN,
  ASTEROID_SPAWN_RATE_SECONDS,
  CHIP_HEALTH_PER_TIER,
  CLICK_DAMAGE_BASE,
  DRONE_FIRE_INTERVAL_S,
  DRONE_ORBIT_RADIUS,
  DRONE_ORBIT_SPEED,
  DRONE_SHOT_SPEED,
  FIRE_RATE_MULT_PER_LEVEL,
  INCOME_MULT_PER_LEVEL,
  MAX_DT,
  NANOBLADE_MULT_PER_LEVEL,
  COLLISION_RESTITUTION,
  PLAYER_INVULNERABILITY_SECONDS,
  PLAYER_LINEAR_DAMPING,
  PLAYER_MASS,
  PLAYER_MAX_SPEED,
  PLAYER_RADIUS,
  PLAYER_RETRO_FACTOR,
  PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS,
  PLAYER_SHOOT_COOLDOWN_SECONDS,
  PLAYER_SHOOT_SPEED,
  PLAYER_START_LIVES,
  PLAYER_THRUST_ACCEL,
  PLAYER_TURN_SPEED,
  POWERUP_CHRONO_SLOW,
  POWERUP_DRIFT_SPEED,
  POWERUP_DROP_CHANCE,
  POWERUP_DURATION_S,
  POWERUP_GOLD_RUSH_MULT,
  POWERUP_OVERDRIVE_MULT,
  POWERUP_PER_USE_PRICE_GROWTH,
  POWERUP_RADIUS,
  POWERUP_RAPID_COOLDOWN_MULT,
  POWERUP_SHIELD_HITS,
  POWERUP_TRIPLE_SPREAD,
  POWERUPS,
  SCREEN_HEIGHT,
  SCREEN_WIDTH,
  SHOT_RADIUS,
  SCORE_LARGE,
  SCORE_MEDIUM,
  SCORE_SMALL,
  UPGRADE_COSTS,
  WAVE_SPAWN_DECAY,
  WAVE_SPAWN_INTERVAL_FLOOR,
  WAVE_SPEED_MAX_STEP,
  WAVE_SPEED_MIN_STEP,
} from "./constants";
import type {
  BoughtPowerUpName,
  PowerUpKind,
  UpgradeName,
} from "./constants";
import type {
  Controls,
  DroneSnap,
  EconomySnap,
  GameEvent,
  Phase,
  PlayerSnap,
  PowerUpSnap,
  ShopSlot,
  ShotSnap,
  Snapshot,
  AsteroidSnap,
} from "./protocol";
import type { Rng } from "./rng";
import { mulberry32 } from "./rng";

// ---------------------------------------------------------------------------
// World state — plain, serializable data
// ---------------------------------------------------------------------------

export interface Vec2 {
  x: number;
  y: number;
}

export interface PlayerState {
  id: string;
  name: string;
  x: number;
  y: number;
  /** Actual per-tick motion for client interpolation. */
  vx: number;
  vy: number;
  rotation: number; // degrees
  /** Hull radius (player.py's CircleShape.radius): the wrap margin and the
   * ship's side of every contact overlap. */
  radius: number;
  /** 0 = ship gone: the player is out and spectates until the run ends. */
  lives: number;
  score: number;
  shotCooldownTimer: number;
  invulnerabilityTimer: number;
  /** Timed pickups (F4): kind -> seconds remaining, dt-decremented. */
  powerupTimers: Partial<Record<PowerUpKind, number>>;
  shieldHits: number;
}

export interface AsteroidState {
  id: number;
  x: number;
  y: number;
  /** Base velocity — the chrono scale applies at movement time. */
  vx: number;
  vy: number;
  radius: number;
  /** Accumulated click-chip damage (idle core). */
  chipDamage: number;
  // No `despawned` flag: the Python main loop needed it to tell culls from
  // paid destruction in its frame-to-frame group diff. Here every kill mints
  // at the destruction site and culls are a separate code path, so the flag
  // has no reader left.
}

export interface ShotState {
  id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** Player id for score attribution; null for drone shots. */
  owner: string | null;
}

export interface PowerUpState {
  id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  kind: PowerUpKind;
}

export interface DroneTurretState {
  orbitAngle: number; // degrees
  fireTimer: number;
}

export interface FieldState {
  spawnTimer: number;
  /** Asteroids spawned in the current wave — the wave-advance guard. */
  spawnedThisWave: number;
}

export interface EconomyState {
  credits: number;
  levels: Record<UpgradeName, number>;
  powerupUses: Partial<Record<BoughtPowerUpName, number>>;
  powerupTimers: Partial<Record<BoughtPowerUpName, number>>;
}

export interface World {
  players: Record<string, PlayerState>;
  asteroids: AsteroidState[];
  shots: ShotState[];
  powerups: PowerUpState[];
  drones: DroneTurretState[];
  economy: EconomyState;
  field: FieldState;
  wave: number;
  phase: Phase;
  /** Chrono dilation published each tick; applied on the NEXT tick's
   * movement, exactly like the Python main loop's class-attribute write. */
  speedScale: number;
  rng: Rng;
  nextEntityId: number;
  /** Rocks destroyed since the last drain — the destruction-diff queue.
   * Mints run at the end of the tick, after the economy's timers tick,
   * matching the Python main loop's ordering exactly. */
  pendingMints: AsteroidState[];
}

/** Difficulty for a wave, pure so tests pin the math directly (F3). */
export interface WaveParams {
  spawnInterval: number;
  speedMin: number;
  speedMax: number;
}

// ---------------------------------------------------------------------------
// newWorld / players
// ---------------------------------------------------------------------------

export function newWorld(seed: number): World {
  return {
    players: {},
    asteroids: [],
    shots: [],
    powerups: [],
    drones: [],
    economy: {
      credits: 0,
      levels: { nanoblade: 0, fire_rate: 0, income: 0, drone: 0 },
      powerupUses: {},
      powerupTimers: {},
    },
    field: { spawnTimer: 0, spawnedThisWave: 0 },
    wave: 1,
    phase: "playing",
    speedScale: 1,
    rng: mulberry32(seed),
    nextEntityId: 1,
    pendingMints: [],
  };
}

/** Seat a player: a fresh ship at the center with the respawn grace window
 * (a late joiner can materialize on top of a live rock mid-wave — the
 * invulnerability is what makes spawning inside a rock survivable). */
export function addPlayer(w: World, id: string, name: string): void {
  w.players[id] = {
    id,
    name,
    x: SCREEN_WIDTH / 2,
    y: SCREEN_HEIGHT / 2,
    vx: 0,
    vy: 0,
    rotation: 0,
    radius: PLAYER_RADIUS,
    lives: PLAYER_START_LIVES,
    score: 0,
    shotCooldownTimer: 0,
    invulnerabilityTimer: PLAYER_INVULNERABILITY_SECONDS,
    powerupTimers: {},
    shieldHits: 0,
  };
}

/** A disconnecting player's ship leaves the world; the room continues. */
export function removePlayer(w: World, id: string): void {
  delete w.players[id];
}

function alivePlayers(w: World): PlayerState[] {
  const out: PlayerState[] = [];
  for (const id of Object.keys(w.players)) {
    const p = w.players[id];
    if (p && p.lives > 0) out.push(p);
  }
  return out;
}

function allPlayersDead(w: World): boolean {
  const ids = Object.keys(w.players);
  if (ids.length === 0) return false;
  return ids.every((id) => (w.players[id]?.lives ?? 0) <= 0);
}

// ---------------------------------------------------------------------------
// Derived economy math (Economy.py's seams, read live from the ledger)
// ---------------------------------------------------------------------------

/** Exponential curve: cost(n) = base × growth**n at the current level. */
export function upgradeCost(e: EconomyState, name: UpgradeName): number {
  const [base, growth] = UPGRADE_COSTS[name];
  return base * growth ** e.levels[name];
}

/** Escalating per-use price: base cost × 1.25 ** uses so far. */
export function powerupPrice(e: EconomyState, name: BoughtPowerUpName): number {
  return POWERUPS[name].cost * POWERUP_PER_USE_PRICE_GROWTH ** (e.powerupUses[name] ?? 0);
}

function goldRushMult(e: EconomyState): number {
  return e.powerupTimers.gold_rush !== undefined ? POWERUP_GOLD_RUSH_MULT : 1;
}

function overdriveMult(e: EconomyState): number {
  return e.powerupTimers.overdrive !== undefined ? POWERUP_OVERDRIVE_MULT : 1;
}

/** Scale factor applied to every mint: the Income upgrade compounds per
 * level; an active Gold Rush multiplies the whole seam, stacking. */
export function incomeMultiplier(e: EconomyState): number {
  return INCOME_MULT_PER_LEVEL ** e.levels.income * goldRushMult(e);
}

/** Chip damage per click: base × Nanoblade levels × Overdrive. Shots never
 * route here — they keep their instant-kill split(). */
export function clickDamage(e: EconomyState): number {
  return CLICK_DAMAGE_BASE * NANOBLADE_MULT_PER_LEVEL ** e.levels.nanoblade * overdriveMult(e);
}

/** Chip damage a rock absorbs before dying, by size tier. */
export function chipThreshold(asteroid: AsteroidState): number {
  const tier = Math.max(1, Math.round(asteroid.radius / ASTEROID_MIN_RADIUS));
  return tier * CHIP_HEALTH_PER_TIER;
}

/** Points for destroying an asteroid, by size tier: smaller rocks pay more. */
export function pointsFor(radius: number): number {
  if (radius >= ASTEROID_MIN_RADIUS * 3) return SCORE_LARGE;
  if (radius >= ASTEROID_MIN_RADIUS * 2) return SCORE_MEDIUM;
  return SCORE_SMALL;
}

/** Spawn cadence and speed band for a wave (F3) — pure, pinned by tests. */
export function waveParams(wave: number): WaveParams {
  return {
    spawnInterval: Math.max(
      WAVE_SPAWN_INTERVAL_FLOOR,
      ASTEROID_SPAWN_RATE_SECONDS * WAVE_SPAWN_DECAY ** (wave - 1),
    ),
    speedMin: ASTEROID_SPEED_MIN + WAVE_SPEED_MIN_STEP * (wave - 1),
    speedMax: ASTEROID_SPEED_MAX + WAVE_SPEED_MAX_STEP * (wave - 1),
  };
}

// ---------------------------------------------------------------------------
// Pure drop decisions (powerups.py) — the sweep consumes these with rolls
// ---------------------------------------------------------------------------

/** A destroyed non-small rock drops a pickup POWERUP_DROP_CHANCE of the
 * time. Strict `<` puts the boundary roll on the no-drop side. */
export function dropsPowerup(radius: number, roll: number): boolean {
  return radius > ASTEROID_MIN_RADIUS && roll < POWERUP_DROP_CHANCE;
}

const POWERUP_TYPES: readonly PowerUpKind[] = ["shield", "rapid", "triple"];

/** Pure uniform type selection: a [0, 1) roll maps evenly across
 * POWERUP_TYPES, clamped so even a sloppy 1.0 roll picks a real type. */
export function pickPowerupType(roll: number): PowerUpKind {
  const index = Math.min(Math.floor(roll * POWERUP_TYPES.length), POWERUP_TYPES.length - 1);
  const kind = POWERUP_TYPES[index];
  return kind === undefined ? "shield" : kind;
}

// ---------------------------------------------------------------------------
// Geometry (circleshape.py + pygame.Vector2.rotate semantics)
// ---------------------------------------------------------------------------

/** pygame.Vector2.rotate: the standard CCW matrix (verified against
 * pygame 2.6.1 this session — screen-space appearance is the client's
 * concern; the numbers here match the desktop build's trajectories). */
export function rotateDeg(v: Vec2, degrees: number): Vec2 {
  const r = (degrees * Math.PI) / 180;
  const cos = Math.cos(r);
  const sin = Math.sin(r);
  return { x: v.x * cos - v.y * sin, y: v.x * sin + v.y * cos };
}

const UP: Vec2 = { x: 0, y: 1 };

function collides(ax: number, ay: number, ar: number, bx: number, by: number, br: number): boolean {
  return Math.hypot(ax - bx, ay - by) <= ar + br;
}

// ---------------------------------------------------------------------------
// Contact physics (circleshape.py, physics overhaul)
// ---------------------------------------------------------------------------

/** Any body the contact math can push: the ship and every rock satisfy this
 * structurally — positions and velocities are mutated in place. */
export interface ImpulseBody {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
}

/** Rock mass model (asteroid.py's inverse_mass): rocks weigh by area —
 * mass = (radius / ASTEROID_MIN_RADIUS)^2 — so a large rock outweighs a
 * small one nine to one and the contact math moves the light one more. */
export function asteroidInverseMass(radius: number): number {
  return (ASTEROID_MIN_RADIUS / radius) ** 2;
}

/** The ship's resistance to an impulse (player.py's inverse_mass): one
 * small rock's worth of inertia, so a large rock's hit shoves the ship
 * hard while the rock barely notices. */
export const PLAYER_INVERSE_MASS = 1.0 / PLAYER_MASS;

/**
 * Pure impulse resolution along the center-to-center normal — the
 * circleshape.resolveContact mirror, the one math every contact pass
 * shares. Approaching bodies exchange an impulse proportional to their
 * closing speed — restitution `e` scales the bounce, so momentum is
 * conserved exactly along the normal while a (1 − e²) share of the pair's
 * kinetic energy dissipates. Both bodies are then pushed apart along the
 * normal by the full overlap, split by inverse mass: a light body gives
 * way, an immovable one (inverse mass 0) doesn't move at all. A
 * separating contact only de-penetrates — no impulse can add speed to
 * bodies already flying apart.
 *
 * The velocity scales fold the chrono dilation into the momentum each
 * body carries into the contact: a chrono-slowed rock hits with its
 * dilated speed (asteroid.py's effective_velocity), not its base one. The
 * ship passes 1.
 *
 * Pure by contract: velocities and positions in, velocities and positions
 * out — never a kill, never a mint, never an event. Returns the applied
 * impulse (0.0 for a de-penetration-only contact), or null when the
 * bodies aren't touching, or when both are immovable and nothing can
 * respond.
 */
export function resolveContact(
  a: ImpulseBody,
  b: ImpulseBody,
  aInverseMass: number,
  bInverseMass: number,
  aVelScale = 1,
  bVelScale = 1,
  e: number = COLLISION_RESTITUTION,
): number | null {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const dist = Math.hypot(dx, dy);
  const overlap = a.radius + b.radius - dist;
  if (overlap <= 0) return null; // not touching — nothing to resolve
  const nx = dist > 0 ? dx / dist : 1;
  const ny = dist > 0 ? dy / dist : 0;
  const totalInv = aInverseMass + bInverseMass;
  if (totalInv <= 0) return null; // two immovable bodies: nothing can respond
  let impulse = 0;
  const closing = (b.vx * bVelScale - a.vx * aVelScale) * nx + (b.vy * bVelScale - a.vy * aVelScale) * ny;
  if (closing < 0) {
    // approaching; separating contacts just de-penetrate
    impulse = (-(1 + e) * closing) / totalInv;
    a.vx -= impulse * aInverseMass * nx;
    a.vy -= impulse * aInverseMass * ny;
    b.vx += impulse * bInverseMass * nx;
    b.vy += impulse * bInverseMass * ny;
  }
  a.x -= nx * overlap * (aInverseMass / totalInv);
  a.y -= ny * overlap * (aInverseMass / totalInv);
  b.x += nx * overlap * (bInverseMass / totalInv);
  b.y += ny * overlap * (bInverseMass / totalInv);
  return impulse;
}

/** Ship-only screen wrap (player.py's wrap): the hull radius is the margin
 * — the ship fully leaves one side before re-entering the other. Rocks,
 * shots, and pickups cull instead, so wrap never leaves the ship. */
function wrapPlayer(p: PlayerState): void {
  const margin = p.radius;
  if (p.x < -margin) {
    p.x = SCREEN_WIDTH + margin;
  } else if (p.x > SCREEN_WIDTH + margin) {
    p.x = -margin;
  }
  if (p.y < -margin) {
    p.y = SCREEN_HEIGHT + margin;
  } else if (p.y > SCREEN_HEIGHT + margin) {
    p.y = -margin;
  }
}

/** True once fully outside the screen bounds by `margin` on any side. */
function offScreen(x: number, y: number, margin: number): boolean {
  return x < -margin || x > SCREEN_WIDTH + margin || y < -margin || y > SCREEN_HEIGHT + margin;
}

/** Python random.randint(a, b): inclusive on both ends. */
function rngInt(w: World, min: number, max: number): number {
  return min + Math.floor(w.rng() * (max - min + 1));
}

// ---------------------------------------------------------------------------
// Mutators
// ---------------------------------------------------------------------------

function removeAsteroid(w: World, asteroid: AsteroidState): void {
  const index = w.asteroids.indexOf(asteroid);
  if (index >= 0) w.asteroids.splice(index, 1);
}

function removeShot(w: World, shot: ShotState): void {
  const index = w.shots.indexOf(shot);
  if (index >= 0) w.shots.splice(index, 1);
}

function removePowerup(w: World, powerup: PowerUpState): void {
  const index = w.powerups.indexOf(powerup);
  if (index >= 0) w.powerups.splice(index, 1);
}

function spawnPowerup(w: World, x: number, y: number, kind: PowerUpKind): void {
  // Slow drift in a random direction: the drop lingers near the rock's
  // death site instead of hanging motionless inside it.
  const dir = rotateDeg(UP, w.rng() * 360);
  w.powerups.push({
    id: w.nextEntityId++,
    x,
    y,
    vx: dir.x * POWERUP_DRIFT_SPEED,
    vy: dir.y * POWERUP_DRIFT_SPEED,
    kind,
  });
}

/** Split a rock into two ×1.2 children one tier down (±20–50°). Small rocks
 * vanish outright. Returns the children; the caller removed the parent. */
function splitAsteroid(w: World, asteroid: AsteroidState): AsteroidState[] {
  if (asteroid.radius <= ASTEROID_MIN_RADIUS) return [];
  const angle = 20 + w.rng() * 30; // Python: random.uniform(20, 50)
  const radius = asteroid.radius - ASTEROID_MIN_RADIUS;
  const children: AsteroidState[] = [];
  // Each child flies along the PARENT'S VELOCITY rotated ±angle (asteroid.py
  // split()), scaled ×1.2 — never along the parent's position vector.
  for (const sign of [1, -1] as const) {
    const dir = rotateDeg({ x: asteroid.vx, y: asteroid.vy }, angle * sign);
    children.push({
      id: w.nextEntityId++,
      x: asteroid.x,
      y: asteroid.y,
      vx: dir.x * 1.2,
      vy: dir.y * 1.2,
      radius,
      chipDamage: 0,
    });
  }
  w.asteroids.push(...children);
  return children;
}

function explosionSize(radius: number): 1 | 2 | 3 {
  const tier = Math.min(3, Math.max(1, Math.round(radius / ASTEROID_MIN_RADIUS)));
  return tier as 1 | 2 | 3;
}

/** One destruction pipeline pays every source: the payout scales the score
 * table by the income multiplier. Queued here, drained at the tick's end —
 * the Python build reaches the same result through its frame-to-frame group
 * diff (a cull never mints; a kill mints exactly once, parent only). */
function queueMint(w: World, asteroid: AsteroidState): void {
  w.pendingMints.push(asteroid);
}

function drainMints(w: World, events: GameEvent[]): void {
  for (const wreck of w.pendingMints) {
    const payout = pointsFor(wreck.radius) * incomeMultiplier(w.economy);
    w.economy.credits += payout;
    events.push({ k: "mint", amount: payout, x: wreck.x, y: wreck.y });
  }
  w.pendingMints.length = 0;
}

// ---------------------------------------------------------------------------
// Player update (player.py)
// ---------------------------------------------------------------------------

const NO_CONTROLS: Controls = {
  thrust: false,
  back: false,
  left: false,
  right: false,
  shoot: false,
};

function updatePlayer(w: World, p: PlayerState, c: Controls, dt: number, events: GameEvent[]): void {
  // A frozen frame (a stalled host's clamped tick) steps dt=0: integrate
  // nothing — no thrust, no damping, no cooldown ticks, no trigger pull.
  // Everything below advances only on positive dt.
  if (dt <= 0) return;
  p.shotCooldownTimer -= dt;
  p.invulnerabilityTimer -= dt;
  tickPlayerPowerups(p, dt);

  if (c.left) p.rotation -= PLAYER_TURN_SPEED * dt;
  if (c.right) p.rotation += PLAYER_TURN_SPEED * dt;

  // Newtonian thrust (physics overhaul): W accelerates along the nose, S
  // retro-thrusts at a fraction of it, and the velocity they build
  // persists between frames — releasing the keys leaves the ship coasting
  // on its momentum. (The Python build flips thrust with its REVERSE
  // curse; the web sim carries no curses, so there is no sign to flip.)
  const nose = rotateDeg(UP, p.rotation);
  let ax = 0;
  let ay = 0;
  if (c.thrust) {
    ax += nose.x * PLAYER_THRUST_ACCEL;
    ay += nose.y * PLAYER_THRUST_ACCEL;
  }
  if (c.back) {
    ax -= nose.x * PLAYER_THRUST_ACCEL * PLAYER_RETRO_FACTOR;
    ay -= nose.y * PLAYER_THRUST_ACCEL * PLAYER_RETRO_FACTOR;
  }
  p.vx += ax * dt;
  p.vy += ay * dt;
  // Light linear damping: gentle space drag that bleeds the ship's
  // momentum back toward rest.
  const damp = Math.exp(-PLAYER_LINEAR_DAMPING * dt);
  p.vx *= damp;
  p.vy *= damp;
  // Speed ceiling: anti-tunnel by arithmetic — the worst clamped frame
  // moves PLAYER_MAX_SPEED * MAX_DT = 36 px, inside the 40 px minimum
  // contact overlap, so overlap can't be jumped over.
  const speed = Math.hypot(p.vx, p.vy);
  if (speed > PLAYER_MAX_SPEED) {
    const scale = PLAYER_MAX_SPEED / speed;
    p.vx *= scale;
    p.vy *= scale;
  }
  p.x += p.vx * dt;
  p.y += p.vy * dt;
  // Ship-only wrap: the ship is the one body that re-enters the opposite
  // edge — rocks, shots, and pickups cull, and the mint path depends on
  // that. The hull radius is the margin: the ship fully leaves one side
  // before re-entering the other.
  wrapPlayer(p);

  if (c.shoot) shootPlayer(w, p, events);
}

function tickPlayerPowerups(p: PlayerState, dt: number): void {
  // Expire timed effects: decrement each duration; a type whose clock runs
  // out loses its effect — the shield also loses its unspent hits.
  for (const kind of Object.keys(p.powerupTimers) as PowerUpKind[]) {
    const remaining = p.powerupTimers[kind];
    if (remaining === undefined) continue;
    const left = remaining - dt;
    if (left > 0) {
      p.powerupTimers[kind] = left;
    } else {
      delete p.powerupTimers[kind];
      if (kind === "shield") p.shieldHits = 0;
    }
  }
}

function shootPlayer(w: World, p: PlayerState, events: GameEvent[]): void {
  if (p.shotCooldownTimer > 0) return;
  // Fire-rate levels scale the cooldown (shop) and RAPID cuts it further
  // (F4); the floor keeps a maxed setup from turning the ship into a
  // hitscan laser. Read live from the shared economy — the Python build
  // pushes cooldown_mult onto the ship after every purchase; with one
  // shared ledger the live read is the same value with no push to forget.
  const rapid = (p.powerupTimers.rapid ?? 0) > 0;
  p.shotCooldownTimer = Math.max(
    PLAYER_SHOOT_COOLDOWN_SECONDS *
      FIRE_RATE_MULT_PER_LEVEL ** w.economy.levels.fire_rate *
      (rapid ? POWERUP_RAPID_COOLDOWN_MULT : 1),
    PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS,
  );
  // One blip per trigger pull, even on a TRIPLE volley.
  events.push({ k: "shoot" });
  if ((p.powerupTimers.triple ?? 0) > 0) {
    // Three-way spread: the center shot plus one on each side (F4).
    for (const spread of [-POWERUP_TRIPLE_SPREAD, 0, POWERUP_TRIPLE_SPREAD]) {
      spawnShot(w, p.x, p.y, p.rotation + spread, PLAYER_SHOOT_SPEED, p.id);
    }
  } else {
    spawnShot(w, p.x, p.y, p.rotation, PLAYER_SHOOT_SPEED, p.id);
  }
}

function spawnShot(w: World, x: number, y: number, angleDeg: number, speed: number, owner: string | null): void {
  const dir = rotateDeg(UP, angleDeg);
  w.shots.push({
    id: w.nextEntityId++,
    x,
    y,
    vx: dir.x * speed,
    vy: dir.y * speed,
    owner,
  });
}

// ---------------------------------------------------------------------------
// Asteroid field (asteroidfield.py)
// ---------------------------------------------------------------------------

function updateField(w: World, dt: number): void {
  const params = waveParams(w.wave);
  w.field.spawnTimer += dt;
  if (w.field.spawnTimer > params.spawnInterval) {
    w.field.spawnTimer = 0;
    // Five seeded rolls per spawn, in the Python field's exact order:
    // edge, speed, velocity jitter, position along the edge, size kind.
    const edgeIndex = rngInt(w, 0, 3);
    const speed = rngInt(w, params.speedMin, params.speedMax);
    const jitter = rngInt(w, -30, 30); // the Python field's inline ±30° spread
    const along = w.rng();
    const kind = rngInt(w, 1, ASTEROID_KINDS);
    spawnFieldAsteroid(w, edgeIndex, along, kind, speed, jitter);
  }
}

function spawnFieldAsteroid(w: World, edgeIndex: number, along: number, kind: number, speed: number, jitter: number): void {
  const edge = edgeFor(edgeIndex, along);
  const vel = rotateDeg(edge.normal, jitter);
  w.asteroids.push({
    id: w.nextEntityId++,
    x: edge.x,
    y: edge.y,
    vx: vel.x * speed,
    vy: vel.y * speed,
    radius: ASTEROID_MIN_RADIUS * kind,
    chipDamage: 0,
  });
  w.field.spawnedThisWave += 1;
}

function edgeFor(index: number, along: number): { normal: Vec2; x: number; y: number } {
  // The four spawn edges in the Python field's order, each just off-screen
  // by ASTEROID_MAX_RADIUS, with the inbound normal.
  switch (index) {
    case 0:
      return { normal: { x: 1, y: 0 }, x: -ASTEROID_MAX_RADIUS, y: along * SCREEN_HEIGHT };
    case 1:
      return { normal: { x: -1, y: 0 }, x: SCREEN_WIDTH + ASTEROID_MAX_RADIUS, y: along * SCREEN_HEIGHT };
    case 2:
      return { normal: { x: 0, y: 1 }, x: along * SCREEN_WIDTH, y: -ASTEROID_MAX_RADIUS };
    default:
      return { normal: { x: 0, y: -1 }, x: along * SCREEN_WIDTH, y: SCREEN_HEIGHT + ASTEROID_MAX_RADIUS };
  }
}

// ---------------------------------------------------------------------------
// Drones (drones.py)
// ---------------------------------------------------------------------------

function updateDrones(w: World, dt: number): void {
  // The turret count follows the Drones level every tick — the level in
  // economy.levels.drone is the single source of truth. Turrets keep their
  // creation-time orbit spacing (the Python fleet's exact quirk).
  const level = w.economy.levels.drone;
  while (w.drones.length < level) {
    const index = w.drones.length;
    w.drones.push({
      orbitAngle: ((360 * index) / level) % 360,
      // First shot staggered inside the first interval (never frame one),
      // so N turrets don't volley in lockstep.
      fireTimer: (DRONE_FIRE_INTERVAL_S * (index + 1)) / (level + 1),
    });
  }
  while (w.drones.length > level) w.drones.pop();

  // One fleet for the room: turrets ride the first live ship (solo and
  // co-op both), so drone kills pay the shared ledger for the room.
  const anchor = alivePlayers(w)[0];
  if (!anchor) return;
  for (const turret of w.drones) {
    turret.orbitAngle = (turret.orbitAngle + DRONE_ORBIT_SPEED * dt) % 360;
    turret.fireTimer -= dt;
    if (turret.fireTimer > 0) continue;
    // += keeps any overshoot, so the cadence stays a true interval.
    turret.fireTimer += DRONE_FIRE_INTERVAL_S;
    droneFire(w, turret, anchor);
  }
}

function droneFire(w: World, turret: DroneTurretState, anchor: PlayerState): void {
  const offset = rotateDeg(UP, turret.orbitAngle);
  const muzzle = { x: anchor.x + offset.x * DRONE_ORBIT_RADIUS, y: anchor.y + offset.y * DRONE_ORBIT_RADIUS };
  // Aim at the nearest rock, or straight off the ship's nose.
  const target = nearestAsteroid(w, muzzle.x, muzzle.y);
  const aimed = target ? normalize(target.x - muzzle.x, target.y - muzzle.y) : null;
  const dir = aimed ?? rotateDeg(UP, anchor.rotation);
  // Drone shots carry no owner: they pay the shared ledger, not a
  // personal score.
  w.shots.push({
    id: w.nextEntityId++,
    x: muzzle.x,
    y: muzzle.y,
    vx: dir.x * DRONE_SHOT_SPEED,
    vy: dir.y * DRONE_SHOT_SPEED,
    owner: null,
  });
}

function nearestAsteroid(w: World, x: number, y: number): AsteroidState | null {
  let best: AsteroidState | null = null;
  let bestDist = Infinity;
  for (const asteroid of w.asteroids) {
    const dist = Math.hypot(asteroid.x - x, asteroid.y - y);
    if (dist < bestDist) {
      best = asteroid;
      bestDist = dist;
    }
  }
  return best;
}

function normalize(x: number, y: number): Vec2 | null {
  const len = Math.hypot(x, y);
  if (len <= 0) return null;
  return { x: x / len, y: y / len };
}

// ---------------------------------------------------------------------------
// Collision sweep (main.handle_collisions) — generalized to co-op
// ---------------------------------------------------------------------------

function handleCollisions(w: World, events: GameEvent[], dt: number): void {
  // Rock↔rock pair pass (physics overhaul): every overlapping pair bounces
  // and separates through the pure contact helper before any game rule
  // reads the field. Physics-only by contract — never a kill (a removed
  // rock would mint a phantom payout through the destruction pipeline
  // downstream), never an event. Chrono-slowed rocks contact at their
  // dilated speed, so slow motion hits heavy, not floaty. A frozen frame
  // (dt = 0) resolves nothing, like every other integrator.
  if (dt > 0) {
    for (let i = 0; i < w.asteroids.length; i++) {
      for (let k = i + 1; k < w.asteroids.length; k++) {
        const a = w.asteroids[i]!;
        const b = w.asteroids[k]!;
        resolveContact(
          a, b,
          asteroidInverseMass(a.radius),
          asteroidInverseMass(b.radius),
          w.speedScale, w.speedScale,
        );
      }
    }
  }

  // Snapshot semantics mirror pygame Group iteration (a copy at loop
  // start): split children born mid-sweep wait for the next tick.
  const rocks = [...w.asteroids];

  for (const asteroid of rocks) {
    // The ship is checked before the shots for each rock, and
    // invulnerability before any hit resolves — a respawning ship can sit
    // inside an asteroid for the grace window without losing a life.
    if (w.phase === "playing") {
      for (const p of alivePlayers(w)) {
        if (p.invulnerabilityTimer > 0) continue;
        if (!collides(asteroid.x, asteroid.y, asteroid.radius, p.x, p.y, p.radius)) continue;
        // Physics before rules (physics overhaul): the contact shoves
        // both bodies along the normal — the rock's inertia resists, the
        // ship's doesn't — before the hit flow prices the collision. A
        // frozen frame shoves nothing; the rules hook below is exactly
        // where it always was.
        if (dt > 0) {
          resolveContact(
            p, asteroid,
            PLAYER_INVERSE_MASS,
            asteroidInverseMass(asteroid.radius),
            1, w.speedScale,
          );
        }
        playerHit(w, p, events);
      }
    }
    for (const shot of [...w.shots]) {
      if (!collides(asteroid.x, asteroid.y, asteroid.radius, shot.x, shot.y, SHOT_RADIUS)) continue;
      removeShot(w, shot);
      shotKill(w, asteroid, shot, events);
      break; // the hit killed the asteroid; skip its remaining shots
    }
  }

  // Pickups collect on player overlap — during play only, mirroring the
  // hit branch: a dead run grants nothing (F4).
  if (w.phase === "playing") {
    for (const powerup of [...w.powerups]) {
      for (const p of alivePlayers(w)) {
        if (!collides(powerup.x, powerup.y, POWERUP_RADIUS, p.x, p.y, PLAYER_RADIUS)) continue;
        removePowerup(w, powerup);
        collectPowerup(p, powerup.kind, events);
        break;
      }
    }
  }
}

/** A live (playing) collision reached the ship: a stocked shield eats it
 * first — the charge is spent, no life lost, no respawn (F4) — otherwise it
 * costs one of the lives. */
function playerHit(w: World, p: PlayerState, events: GameEvent[]): void {
  if (p.shieldHits > 0) {
    p.shieldHits -= 1;
    return; // absorbed: nothing visible happens (the Python build logs it only)
  }
  events.push({ k: "playerHit", playerId: p.id, x: p.x, y: p.y });
  p.lives -= 1;
  if (p.lives <= 0) {
    p.lives = 0;
    // Co-op pluralizes the Python game-over: the run ends when EVERY
    // player is out, not the first.
    if (allPlayersDead(w)) {
      w.phase = "game_over";
      events.push({ k: "gameOver" });
    }
  } else {
    respawnPlayer(p);
  }
}

function respawnPlayer(p: PlayerState): void {
  // Center the ship, zero its velocity, grant the grace window.
  p.x = SCREEN_WIDTH / 2;
  p.y = SCREEN_HEIGHT / 2;
  p.vx = 0;
  p.vy = 0;
  p.invulnerabilityTimer = PLAYER_INVULNERABILITY_SECONDS;
}

function shotKill(w: World, asteroid: AsteroidState, shot: ShotState, events: GameEvent[]): void {
  // One destruction path: burst the parent at its death site (any size),
  // split it, score the shooter, mint credits, roll for a pickup.
  events.push({ k: "explosion", size: explosionSize(asteroid.radius), x: asteroid.x, y: asteroid.y });
  removeAsteroid(w, asteroid);
  splitAsteroid(w, asteroid);
  if (shot.owner !== null) {
    const owner = w.players[shot.owner];
    if (owner) owner.score += pointsFor(asteroid.radius);
  }
  queueMint(w, asteroid);
  // A destroyed non-small rock occasionally pays a pickup (F4) — rolls in
  // the Python sweep's order: drop chance, then type, then drift angle.
  if (dropsPowerup(asteroid.radius, w.rng())) {
    spawnPowerup(w, asteroid.x, asteroid.y, pickPowerupType(w.rng()));
  }
}

function collectPowerup(p: PlayerState, kind: PowerUpKind, events: GameEvent[]): void {
  // (Re)arm its duration from the constants table; the shield stocks its
  // hit count. Data-driven (F4): retunes touch constants, not this code.
  p.powerupTimers[kind] = POWERUP_DURATION_S[kind];
  if (kind === "shield") p.shieldHits = POWERUP_SHIELD_HITS;
  events.push({ k: "pickup", kind });
}

// ---------------------------------------------------------------------------
// Wave guard, economy tick, restart (main.py / game.py)
// ---------------------------------------------------------------------------

function maybeAdvanceWave(w: World, events: GameEvent[]): void {
  // Start the next wave once the current one was populated and is cleared
  // (F3). The populated guard is the trap at both ends of a run: at game
  // start and after a restart the field is empty with wave at 1 — without
  // it the counter would immediately tick to 2. Game over advances nothing.
  if (w.phase !== "playing") return;
  if (w.field.spawnedThisWave === 0 || w.asteroids.length > 0) return;
  w.wave += 1;
  w.field.spawnTimer = 0;
  w.field.spawnedThisWave = 0;
  events.push({ k: "waveStarted", wave: w.wave });
}

function tickEconomyPowerups(w: World, dt: number): void {
  // Expire bought timed effects on the dt-timer pattern: every effect
  // reads its multiplier live, so expiry restores base values by itself.
  for (const name of Object.keys(w.economy.powerupTimers) as BoughtPowerUpName[]) {
    const remaining = w.economy.powerupTimers[name];
    if (remaining === undefined) continue;
    const left = remaining - dt;
    if (left > 0) {
      w.economy.powerupTimers[name] = left;
    } else {
      delete w.economy.powerupTimers[name];
    }
  }
  // Publish the chrono scale for the NEXT tick's movement — the Python
  // main loop writes it after ticking timers, so an activation takes
  // effect on the following frame exactly like this.
  w.speedScale = w.economy.powerupTimers.chrono !== undefined ? POWERUP_CHRONO_SLOW : 1;
}

// ---------------------------------------------------------------------------
// Message intents — buy / click / restart (shop.py + main.py's event pump)
// ---------------------------------------------------------------------------

const UPGRADE_BY_SLOT: Partial<Record<ShopSlot, UpgradeName>> = {
  1: "nanoblade",
  2: "fire_rate",
  3: "income",
  4: "drone",
};

const POWERUP_BY_SLOT: Partial<Record<ShopSlot, BoughtPowerUpName>> = {
  7: "gold_rush",
  8: "nuke",
  9: "overdrive",
  0: "chrono",
};

/** One level of an upgrade, or one activation of a powerup, through the
 * Economy seams — server-gated in rooms, direct in solo. A short ledger
 * changes nothing and returns no events (the panel's dim styling is what
 * tells the player, as in the Python build). */
export function buy(w: World, slot: ShopSlot): GameEvent[] {
  const events: GameEvent[] = [];
  const upgradeName = UPGRADE_BY_SLOT[slot];
  if (upgradeName) {
    const cost = upgradeCost(w.economy, upgradeName);
    if (w.economy.credits < cost) return events;
    w.economy.credits -= cost;
    w.economy.levels[upgradeName] += 1;
    events.push({ k: "purchase", what: upgradeName });
    return events;
  }
  const powerupName = POWERUP_BY_SLOT[slot];
  if (!powerupName) return events;
  const price = powerupPrice(w.economy, powerupName);
  if (w.economy.credits < price) return events;
  w.economy.credits -= price;
  w.economy.powerupUses[powerupName] = (w.economy.powerupUses[powerupName] ?? 0) + 1;
  const duration = POWERUPS[powerupName].duration;
  if (duration > 0) w.economy.powerupTimers[powerupName] = duration;
  events.push({ k: "purchase", what: powerupName });
  // The nuke is the one activation that also destroys — through the normal
  // splits, so the destruction pipeline mints each rock exactly once. The
  // event pump runs before the frame's destruction diff (Python ordering),
  // so the intent call drains its own queue before returning — same as
  // clickAt.
  if (powerupName === "nuke") {
    events.push(...nukeField(w));
    drainMints(w, events);
  }
  return events;
}

/** Click-to-chip: the zero-radius cursor probe (main.asteroid_at), nearest
 * rock wins. Chip damage accrues per click and a crossed threshold dies
 * through the normal split path — minted credits, no score (the Python
 * sweep scores shots only), no burst, no drop roll. */
export function clickAt(w: World, x: number, y: number): GameEvent[] {
  const events: GameEvent[] = [];
  let best: AsteroidState | null = null;
  let bestDist = Infinity;
  for (const asteroid of w.asteroids) {
    if (!collides(asteroid.x, asteroid.y, asteroid.radius, x, y, 0)) continue;
    const dist = Math.hypot(asteroid.x - x, asteroid.y - y);
    if (dist < bestDist) {
      best = asteroid;
      bestDist = dist;
    }
  }
  if (!best) return events;
  best.chipDamage += clickDamage(w.economy);
  if (best.chipDamage >= chipThreshold(best)) {
    removeAsteroid(w, best);
    splitAsteroid(w, best);
    queueMint(w, best);
  }
  // Python mints in the same frame's destruction diff — the event pump runs
  // before it — so the intent call drains its own queue before returning.
  drainMints(w, events);
  return events;
}

function nukeField(w: World): GameEvent[] {
  // The nuke: split the whole field to completion, right now. Every rock
  // dies through the ordinary split path — no free pass and no second mint
  // path. Children born inside this call were never on screen in any frame
  // snapshot, so only the rocks that were on screen mint, exactly once.
  const originals = [...w.asteroids];
  let frontier = originals.slice();
  while (frontier.length > 0) {
    const next: AsteroidState[] = [];
    for (const rock of frontier) {
      removeAsteroid(w, rock);
      next.push(...splitAsteroid(w, rock));
    }
    frontier = next;
  }
  const events: GameEvent[] = [];
  for (const rock of originals) {
    // Debris only: the Python nuke bursts every rock but never plays a
    // sound — the client renders `burst` without SFX.
    events.push({ k: "burst", x: rock.x, y: rock.y, radius: rock.radius });
    queueMint(w, rock);
  }
  return events;
}

/** Any player's restart from the game-over overlay re-seeds the room: fresh
 * wave 1, the field's clock reset, every ship back with full lives. Mirrors
 * Game.restart + the main-loop reset block: run counters to zero, world
 * cleared, player powerups wiped, bought-effect timers ended (paid uses
 * stay consumed — credits, levels, and use counts persist across runs,
 * exactly like the desktop economy). */
export function requestRestart(w: World): GameEvent[] {
  if (w.phase !== "game_over") return [];
  w.asteroids = [];
  w.shots = [];
  w.powerups = [];
  for (const id of Object.keys(w.players)) {
    const p = w.players[id];
    if (!p) continue;
    p.powerupTimers = {};
    p.shieldHits = 0;
    p.score = 0;
    p.lives = PLAYER_START_LIVES;
    respawnPlayer(p);
  }
  w.economy.powerupTimers = {}; // end_run_effects
  w.wave = 1;
  w.phase = "playing";
  w.field.spawnTimer = 0;
  w.field.spawnedThisWave = 0;
  return [{ k: "waveStarted", wave: 1 }];
}

// ---------------------------------------------------------------------------
// step — one fixed tick (main.py's loop body, same ordering)
// ---------------------------------------------------------------------------

export function step(w: World, dt: number, inputs: Record<string, Controls>): GameEvent[] {
  const events: GameEvent[] = [];
  // MAX_DT bounds a single step (constants.py:22): a stalled host must
  // never move entities far enough to tunnel through a collision.
  const stepDt = Math.min(Math.max(dt, 0), MAX_DT);

  // Snapshots of the live lists mirror pygame's group iteration: sprites
  // created during this tick (shots fired, rocks spawned) wait for the
  // next one to move.
  const rocks = [...w.asteroids];
  const shots = [...w.shots];
  const pickups = [...w.powerups];

  for (const id of Object.keys(w.players)) {
    const p = w.players[id];
    if (!p || p.lives <= 0) continue; // out of lives = no ship (co-op spectate)
    updatePlayer(w, p, inputs[id] ?? NO_CONTROLS, stepDt, events);
  }

  updateField(w, stepDt);

  for (const asteroid of rocks) {
    // Chrono time dilation rides the step: the active scale (1.0 baseline)
    // was published at the end of the previous tick.
    asteroid.x += asteroid.vx * w.speedScale * stepDt;
    asteroid.y += asteroid.vy * w.speedScale * stepDt;
    if (offScreen(asteroid.x, asteroid.y, ASTEROID_MAX_RADIUS)) {
      // A rock that drifted off-screen was never destroyed — culled
      // without a mint.
      removeAsteroid(w, asteroid);
    }
  }

  for (const shot of shots) {
    shot.x += shot.vx * stepDt;
    shot.y += shot.vy * stepDt;
    if (offScreen(shot.x, shot.y, ASTEROID_MAX_RADIUS)) removeShot(w, shot);
  }

  for (const powerup of pickups) {
    powerup.x += powerup.vx * stepDt;
    powerup.y += powerup.vy * stepDt;
    if (offScreen(powerup.x, powerup.y, POWERUP_RADIUS)) removePowerup(w, powerup);
  }

  updateDrones(w, stepDt);

  handleCollisions(w, events, stepDt);
  maybeAdvanceWave(w, events);
  tickEconomyPowerups(w, stepDt);

  // Destruction → credits: drain the tick's wrecks after the economy's
  // timers tick — the Python main loop's exact mint ordering.
  drainMints(w, events);
  return events;
}

// ---------------------------------------------------------------------------
// snapshot — the wire form (plain JSON-safe data, no shared references)
// ---------------------------------------------------------------------------

export function snapshot(w: World): Snapshot {
  const players: PlayerSnap[] = [];
  for (const id of Object.keys(w.players)) {
    const p = w.players[id];
    if (!p) continue;
    players.push({
      id: p.id,
      name: p.name,
      x: p.x,
      y: p.y,
      vx: p.vx,
      vy: p.vy,
      rotation: p.rotation,
      lives: p.lives,
      score: p.score,
      invulnTimer: p.invulnerabilityTimer,
      shieldHits: p.shieldHits,
    });
  }
  const anchor = alivePlayers(w)[0];
  const drones: DroneSnap[] = w.drones.map((t) => ({
    orbitAngle: t.orbitAngle,
    anchorId: anchor ? anchor.id : null,
  }));
  const asteroids: AsteroidSnap[] = w.asteroids.map((a) => ({
    id: a.id,
    x: a.x,
    y: a.y,
    // Effective velocity (chrono applied) so client extrapolation matches
    // the sim's actual motion.
    vx: a.vx * w.speedScale,
    vy: a.vy * w.speedScale,
    radius: a.radius,
  }));
  const shots: ShotSnap[] = w.shots.map((s) => ({ id: s.id, x: s.x, y: s.y, vx: s.vx, vy: s.vy }));
  const powerups: PowerUpSnap[] = w.powerups.map((pu) => ({ id: pu.id, x: pu.x, y: pu.y, kind: pu.kind }));
  const economy: EconomySnap = {
    credits: w.economy.credits,
    levels: { ...w.economy.levels },
    powerupUses: { ...w.economy.powerupUses },
    powerupTimers: { ...w.economy.powerupTimers },
  };
  return {
    wave: w.wave,
    phase: w.phase,
    players,
    asteroids,
    shots,
    powerups,
    economy,
    drones,
  };
}
