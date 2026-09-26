/**
 * Semi-3D presentation helpers — the Canvas port of comicfx.py's
 * ship-and-rock shading block. Pure geometry plus the one-time rock bake:
 * per-frame draw cost stays blit + strokes (the V3/V4 composite budget),
 * and every color site resolves through PALETTE upstream.
 *
 * The desktop twin derives its shapes from Python's `random.Random` off the
 * rock's crack_seed well; the web twin derives the same *shape contract*
 * (same bands, same stream discipline) deterministically from the rock's
 * snapshot `id` — same id, identical rock on every client, no protocol
 * change. The three shape aspects reseed their own streams (seed, seed+1,
 * seed+2) so adding an aspect later cannot reshuffle the others.
 */
import {
  ASTEROID_KINDS,
  ASTEROID_MIN_RADIUS,
  ASTEROID_SPIN_MAX_DPS,
  ASTEROID_SPIN_MIN_DPS,
  BANK_RESPONSE_S,
  CANOPY_GLINT_FRACTION,
  CANOPY_RADIUS_X,
  CANOPY_RADIUS_Y,
  CRATER_COUNT,
  CRATER_RADIUS_FRACTION,
  ENGINE_GLOW_HALF_WIDTH,
  ENGINE_GLOW_REACH_IDLE_PX,
  ENGINE_GLOW_REACH_THRUST_PX,
  ENGINE_GLOW_TAIL_INSET,
  ENGINE_GLOW_WIDTH_GAIN,
  PALETTE,
  PLAYER_RADIUS,
  PLAYER_SPEED,
  PLAYER_TURN_SPEED,
  SHIP_SHADOW_OFFSET,
  SILHOUETTE_JITTER,
  SILHOUETTE_LIGHT_ANGLE,
  SILHOUETTE_SHADOW_DEPTH,
  SILHOUETTE_VERTICES,
  THRUST_RESPONSE_S,
} from "../shared/constants";
import type { RGB } from "../shared/constants";
import type { AsteroidSnap, PlayerSnap } from "../shared/protocol";
import { mulberry32 } from "../shared/rng";
import { rotateDeg } from "../shared/sim";
import type { Vec2 } from "../shared/sim";
import { rgbCss } from "./fx";

const UP: Vec2 = { x: 0, y: 1 };

// Size-tier order for the palette lookup: tier 1 (small) → 3 (large) —
// asteroid.py's ASTEROID_COLOR_KEYS plus the shading swatches beside them.
const ASTEROID_COLOR_KEYS = ["asteroid_s", "asteroid_m", "asteroid_l"] as const;
const ASTEROID_SHADOW_KEYS = [
  "asteroid_shadow_s",
  "asteroid_shadow_m",
  "asteroid_shadow_l",
] as const;
const ASTEROID_HIGHLIGHT_KEYS = [
  "asteroid_highlight_s",
  "asteroid_highlight_m",
  "asteroid_highlight_l",
] as const;

// mulberry32 returns [0, 1); these wrap Python's random.Random calls in the
// stream order the desktop helpers draw them — randint (inclusive), uniform,
// and a two-way choice — so ported call sites read line-for-line.
function randInt(rng: () => number, lo: number, hi: number): number {
  return lo + Math.floor(rng() * (hi - lo + 1));
}

function uniform(rng: () => number, lo: number, hi: number): number {
  return lo + rng() * (hi - lo);
}

function sign(rng: () => number): number {
  return rng() < 0.5 ? -1 : 1;
}

/** comicfx.mix_colors — pure color lerp a→b at fraction t (the no-alpha
 * fade house pattern, generalized to any pair of palette entries). */
export function mixColors(a: RGB, b: RGB, t: number): RGB {
  return [
    Math.round(a[0] + (b[0] - a[0]) * t),
    Math.round(a[1] + (b[1] - a[1]) * t),
    Math.round(a[2] + (b[2] - a[2]) * t),
  ];
}

/** comicfx.light_direction — the shared light's screen direction: up-left,
 * the heading the rock bake and the canopy glint both read. */
export function lightDirection(): Vec2 {
  return rotateDeg({ x: 1, y: 0 }, SILHOUETTE_LIGHT_ANGLE);
}

/** comicfx.silhouette_points — the seeded lumpy silhouette: 10–14 vertices
 * at even angle steps, each radius jittered within ±14% of the hull radius,
 * in draw order, relative to the rock center. Deterministic per (radius,
 * seed); the web seed is the rock's snapshot id. */
export function silhouettePoints(radius: number, seed: number): Vec2[] {
  const rng = mulberry32(seed);
  const [vertexLo, vertexHi] = SILHOUETTE_VERTICES;
  const [jitterLo, jitterHi] = SILHOUETTE_JITTER;
  const count = randInt(rng, vertexLo, vertexHi);
  const points: Vec2[] = [];
  for (let i = 0; i < count; i += 1) {
    const heading = (i * 360) / count;
    const jitter = uniform(rng, jitterLo, jitterHi) * sign(rng);
    const dir = rotateDeg({ x: 1, y: 0 }, heading);
    points.push({ x: dir.x * radius * (1 + jitter), y: dir.y * radius * (1 + jitter) });
  }
  return points;
}

/** comicfx.silhouette_radius_at — the lumpy outline's true radius at a
 * heading (ray-polygon reach), so the bake's shadow band parallels the rim
 * between the sparse vertices instead of cutting chords across them. */
export function silhouetteRadiusAt(silhouette: Vec2[], headingDegrees: number): number {
  const dir = rotateDeg({ x: 1, y: 0 }, headingDegrees);
  const count = silhouette.length;
  let best = 0;
  for (let i = 0; i < count; i += 1) {
    const a = silhouette[i];
    const b = silhouette[(i + 1) % count];
    if (!a || !b) continue;
    const edge = { x: b.x - a.x, y: b.y - a.y };
    const denom = dir.x * edge.y - dir.y * edge.x;
    if (Math.abs(denom) < 1e-9) continue; // the ray runs along this edge
    const t = (a.x * edge.y - a.y * edge.x) / denom;
    const s = (dir.y * a.x - dir.x * a.y) / denom;
    if (t > 0 && s >= 0 && s < 1 && t > best) best = t;
  }
  return best;
}

export interface CraterSpec {
  offset: Vec2; // relative to the rock center
  rx: number;
  ry: number;
}

/** comicfx.crater_specs — the seeded crater layout: 2–5 ellipses per rock.
 * Centers stay well inside the hull (≤ 0.62·radius), so a crater and its
 * lit rim never cross even the deepest silhouette dip (0.62 + 0.22 < 0.86). */
export function craterSpecs(radius: number, seed: number): CraterSpec[] {
  const rng = mulberry32(seed + 1); // a stream apart from the silhouette's
  const [countLo, countHi] = CRATER_COUNT;
  const [radiusLo, radiusHi] = CRATER_RADIUS_FRACTION;
  const craters: CraterSpec[] = [];
  for (let i = 0; i < randInt(rng, countLo, countHi); i += 1) {
    const heading = uniform(rng, 0, 360);
    const dist = uniform(rng, 0, 0.62) * radius;
    const dir = rotateDeg({ x: 1, y: 0 }, heading);
    const rx = uniform(rng, radiusLo, radiusHi) * radius;
    const ry = rx * uniform(rng, 0.65, 0.95);
    craters.push({ offset: { x: dir.x * dist, y: dir.y * dist }, rx, ry });
  }
  return craters;
}

/** comicfx.spin_rate_for — the seeded signed spin rate in deg/s: magnitude
 * inside the ASTEROID_SPIN band, direction a coin flip. Presentation-only
 * state the sim never reads. */
export function spinRateFor(seed: number): number {
  const rng = mulberry32(seed + 2); // a stream apart from the shape's
  const rate = uniform(rng, ASTEROID_SPIN_MIN_DPS, ASTEROID_SPIN_MAX_DPS);
  return sign(rng) < 0 ? -rate : rate;
}

/** The body's spin angle at presentation time `now` (seconds, the rAF
 * clock): the seeded rate scaled onto the clock — a pure function of (id,
 * now), so every client tumbles the same rock identically. */
export function spinAngleFor(seed: number, now: number): number {
  return (((spinRateFor(seed) * now) % 360) + 360) % 360;
}

/** asteroid.asteroid_shade_colors — the (tier hue, shadow, highlight) triple
 * a rock's shaded bake resolves through PALETTE, by size tier. */
export function asteroidShadeColors(radius: number): {
  tier: RGB;
  shadow: RGB;
  highlight: RGB;
} {
  const tier = Math.min(ASTEROID_KINDS, Math.max(1, Math.round(radius / ASTEROID_MIN_RADIUS)));
  const tierIndex = tier - 1;
  const colorKey = ASTEROID_COLOR_KEYS[tierIndex];
  const shadowKey = ASTEROID_SHADOW_KEYS[tierIndex];
  const highlightKey = ASTEROID_HIGHLIGHT_KEYS[tierIndex];
  return {
    tier: PALETTE[colorKey ?? "asteroid_s"],
    shadow: PALETTE[shadowKey ?? "asteroid_shadow_s"],
    highlight: PALETTE[highlightKey ?? "asteroid_highlight_s"],
  };
}

/** comicfx.bake_rock_surface — pre-render a rock's shaded body: the
 * silhouette filled with the shadow color, the lit two-band body on top (a
 * 72-heading ring sampling the outline's true radius, pulled radially in by
 * the shadow depth the light misses), the warm highlight arc on the lit
 * side, and the seeded craters. The light is baked in the body's local
 * frame (bake-and-rotate): at spin 0 it shines from up-left on screen, and
 * the bake tumbles with the rock thereafter. Transparent outside the
 * silhouette, opaque inside — per-frame cost stays one rotate + drawImage.
 *
 * Returns null where no DOM canvas exists (node test envs) — callers skip
 * the blit and still draw the ink stack. */
export function bakeRockCanvas(
  radius: number,
  seed: number,
  tierColor: RGB,
  shadowColor: RGB,
  highlightColor: RGB,
): HTMLCanvasElement | null {
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  const pad = 4; // room for the lumpiest vertex past the nominal radius
  const size = Math.round(radius * 2) + pad * 2;
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const center = size / 2;
  const silhouette = silhouettePoints(radius, seed);
  const outer = silhouette.map((v) => ({ x: center + v.x, y: center + v.y }));

  // Two-band cel shading: the shadow color fills the whole silhouette, then
  // the lit body paints on top — hard band edges, no airbrushing (the
  // locked style). The lit ring stays star-shaped (reach ≥ 0.5·radius at
  // every heading), so the top fill is always a simple polygon.
  fillPolygon(ctx, outer, shadowColor);
  const antiLight = SILHOUETTE_LIGHT_ANGLE + 180;
  const steps = 72;
  const lit: Vec2[] = [];
  for (let step = 0; step < steps; step += 1) {
    const heading = (step * 360) / steps;
    const depth =
      SILHOUETTE_SHADOW_DEPTH * radius * Math.max(0, Math.cos(rad(heading - antiLight)));
    const reach = silhouetteRadiusAt(silhouette, heading) - depth;
    lit.push({
      x: center + Math.cos(rad(heading)) * reach,
      y: center + Math.sin(rad(heading)) * reach,
    });
  }
  fillPolygon(ctx, lit, tierColor);

  // The single warm highlight arc on the lit side, inset from the edge.
  const arcRadius = radius * 0.62;
  const arc: Vec2[] = [];
  for (let step = -4; step <= 4; step += 1) {
    const heading = rad(SILHOUETTE_LIGHT_ANGLE + step * 15);
    arc.push({ x: center + Math.cos(heading) * arcRadius, y: center + Math.sin(heading) * arcRadius });
  }
  strokePolyline(ctx, arc, highlightColor, 3);

  // Seeded craters: dark bowls with a lit rim glint on the light-facing
  // edge — surface detail over the shading, beneath the crack web.
  for (const { offset, rx, ry } of craterSpecs(radius, seed)) {
    const bowlX = center + offset.x;
    const bowlY = center + offset.y;
    ctx.beginPath();
    ctx.ellipse(bowlX, bowlY, rx, ry, 0, 0, Math.PI * 2);
    ctx.fillStyle = rgbCss(shadowColor);
    ctx.fill();
    const rim: Vec2[] = [];
    for (let step = -2; step <= 2; step += 1) {
      const heading = rad(SILHOUETTE_LIGHT_ANGLE + step * 30);
      rim.push({
        x: bowlX + Math.cos(heading) * rx * 0.85,
        y: bowlY + Math.sin(heading) * ry * 0.85,
      });
    }
    strokePolyline(ctx, rim, highlightColor, 2);
  }
  return canvas;
}

function rad(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

/** pygame.draw.polygon's filled-polygon analog. */
export function fillPolygon(ctx: CanvasRenderingContext2D, points: Vec2[], color: RGB): void {
  ctx.beginPath();
  points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  ctx.closePath();
  ctx.fillStyle = rgbCss(color);
  ctx.fill();
}

function strokePolyline(
  ctx: CanvasRenderingContext2D,
  points: Vec2[],
  color: RGB,
  width: number,
): void {
  ctx.beginPath();
  points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  ctx.strokeStyle = rgbCss(color);
  ctx.lineWidth = width;
  ctx.stroke();
}

// --- The rock bake cache ----------------------------------------------------
// Bakes key on (id, radius) — the radius rides the key because ids are only
// unique within a session, and the bake is per (shape, size). An LRU cap
// keeps the cache bounded no matter how long a run lasts; a live field's
// rocks re-bake never (hits re-heat their entry).

const bakeCache = new Map<string, HTMLCanvasElement>();
const BAKE_CACHE_MAX = 256;

/** The rock's cached shaded bake — baked once per (id, radius), then reused
 * every frame (the desktop's lazy per-rock Surface). Null without a DOM. */
export function getRockBake(id: number, radius: number): HTMLCanvasElement | null {
  const key = `${id}:${radius}`;
  const hit = bakeCache.get(key);
  if (hit) {
    bakeCache.delete(key);
    bakeCache.set(key, hit); // LRU touch
    return hit;
  }
  const { tier, shadow, highlight } = asteroidShadeColors(radius);
  const bake = bakeRockCanvas(radius, id, tier, shadow, highlight);
  if (!bake) return null;
  bakeCache.set(key, bake);
  if (bakeCache.size > BAKE_CACHE_MAX) {
    const oldest = bakeCache.keys().next().value;
    if (oldest !== undefined) bakeCache.delete(oldest);
  }
  return bake;
}

/** The silhouette in the body's current spin frame, in absolute draw
 * coordinates — the polygon the ink stack traces this frame. rotateDeg(+spin)
 * and canvas ctx.rotate(+spin·rad) share the y-down clockwise-positive
 * convention, so bake and outline tumble in lockstep. */
export function rockInkPoints(a: AsteroidSnap, spin: number): Vec2[] {
  return silhouettePoints(a.radius, a.id).map((v) => {
    const rotated = rotateDeg(v, spin);
    return { x: a.x + rotated.x, y: a.y + rotated.y };
  });
}

// --- Ship presentation clocks -----------------------------------------------
// The bank leans into the current turn (-1..1) and the throttle drives the
// exhaust flame (0..1) — player.py's presentation fields, eased toward their
// per-frame targets. The sim never reads either; the web derives them from
// snapshot fields: bank from the interpolated rotation's frame delta,
// throttle from the ship's velocity along its nose (movePlayer sets vx,vy to
// exactly PLAYER_SPEED along the nose while thrusting, zero at rest).

export interface ShipClockState {
  bank: number;
  thrust: number;
}

interface ShipClockEntry extends ShipClockState {
  prevRotation: number | null;
  prevNow: number | null;
}

const shipClocks = new Map<string, ShipClockEntry>();

// A frame gap longer than this carries no motion information (a respawn's
// 2s absence, a tab stall) — the clock holds instead of easing from stale
// state. Desktop needs no such guard (one continuous local loop).
const CLOCK_GAP_SECONDS = 0.25;

/** Shortest-arc degree delta — the interpolated rotation crosses the
 * 0°/360° seam, and a naive delta would read a 20° turn as -340°. */
function shortestArcDeg(delta: number): number {
  let d = delta % 360;
  if (d > 180) d -= 360;
  if (d < -180) d += 360;
  return d;
}

/** The thrust fraction a snapshot's velocity carries: +PLAYER_SPEED along
 * the nose while thrusting (movePlayer), zero at rest — clamped to 0..1 so
 * interpolation jitter and reverse thrust (desktop lights no plume for it)
 * read as the desktop's 0/1 throttle targets. */
export function thrustTargetFor(p: PlayerSnap): number {
  const nose = rotateDeg(UP, p.rotation);
  const along = (p.vx * nose.x + p.vy * nose.y) / PLAYER_SPEED;
  return Math.max(0, Math.min(1, along));
}

/** Ease the per-ship presentation clocks one frame toward their targets and
 * return them. Call every frame for every drawn ship, blink-dark or not —
 * the desktop eases in update(), not draw(). */
export function updateShipClocks(p: PlayerSnap, now: number): ShipClockState {
  const entry = shipClocks.get(p.id) ?? {
    prevRotation: null,
    prevNow: null,
    bank: 0,
    thrust: 0,
  };
  const dt = entry.prevNow === null ? 0 : now - entry.prevNow;
  if (entry.prevRotation !== null && dt > 0 && dt <= CLOCK_GAP_SECONDS) {
    const delta = shortestArcDeg(p.rotation - entry.prevRotation);
    const turnFraction = delta / (PLAYER_TURN_SPEED * dt);
    const bankTarget = Math.max(-1, Math.min(1, turnFraction));
    entry.bank += (bankTarget - entry.bank) * Math.min(1, dt * BANK_RESPONSE_S);
    const thrustTarget = thrustTargetFor(p);
    entry.thrust += (thrustTarget - entry.thrust) * Math.min(1, dt * THRUST_RESPONSE_S);
  }
  entry.prevRotation = p.rotation;
  entry.prevNow = now;
  shipClocks.set(p.id, entry);
  return { bank: entry.bank, thrust: entry.thrust };
}

/** Drop clock entries for players no longer in the snapshot — dead-state
 * hygiene so the store never grows with the session. */
export function pruneShipClocks(activeIds: string[]): void {
  const live = new Set(activeIds);
  for (const id of shipClocks.keys()) {
    if (!live.has(id)) shipClocks.delete(id);
  }
}

export interface HullBand {
  quad: Vec2[];
  fraction: number; // 0 = tail (pure shade) .. 1 = nose (pure lit)
}

/** comicfx.hull_gradient_bands — the hull triangle tiled into `bands` quads
 * between the tail edge and the nose vertex, each with its gradient
 * fraction. Fractions span the full 0→1 range so the tail band hits the
 * pure shade and the nose band the pure lit color; hard band edges — the
 * cel style the rocks share. */
export function hullGradientBands(nose: Vec2, tailA: Vec2, tailB: Vec2, bands: number): HullBand[] {
  const lerp = (a: Vec2, b: Vec2, t: number): Vec2 => ({
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
  });
  const out: HullBand[] = [];
  for (let i = 0; i < bands; i += 1) {
    const t0 = i / bands;
    const t1 = (i + 1) / bands;
    const a0 = lerp(tailA, nose, t0);
    const a1 = lerp(tailA, nose, t1);
    const b0 = lerp(tailB, nose, t0);
    const b1 = lerp(tailB, nose, t1);
    out.push({ quad: [a0, a1, b1, b0], fraction: bands > 1 ? i / (bands - 1) : 0 });
  }
  return out;
}

/** comicfx.ellipse_points — a rotated ellipse outline (12 segments by
 * default), closed-ready. The ship's canopy must bank and turn with the
 * hull, and the canvas ellipse is axis-aligned only. */
export function ellipsePoints(
  centerX: number,
  centerY: number,
  rx: number,
  ry: number,
  angleDegrees: number,
  segments = 12,
): Vec2[] {
  const points: Vec2[] = [];
  for (let i = 0; i < segments; i += 1) {
    const t = rad((i * 360) / segments);
    const local = { x: Math.cos(t) * rx, y: Math.sin(t) * ry };
    const rotated = rotateDeg(local, angleDegrees);
    points.push({ x: centerX + rotated.x, y: centerY + rotated.y });
  }
  return points;
}

/** The hull's canopy dome (player.py _draw_canopy): an ellipse at the hull's
 * centroid, its long axis across the ship, with the specular glint dot
 * thrown toward the shared light. */
export function canopyPoints(nose: Vec2, tailA: Vec2, tailB: Vec2, rotation: number): Vec2[] {
  const centroid = {
    x: (nose.x + tailA.x + tailB.x) / 3,
    y: (nose.y + tailA.y + tailB.y) / 3,
  };
  return ellipsePoints(
    centroid.x,
    centroid.y,
    PLAYER_RADIUS * CANOPY_RADIUS_X,
    PLAYER_RADIUS * CANOPY_RADIUS_Y,
    rotation + 90,
  );
}

/** The canopy glint's center: the centroid offset toward the shared light
 * by CANOPY_GLINT_FRACTION of the hull radius. */
export function canopyGlintCenter(nose: Vec2, tailA: Vec2, tailB: Vec2): Vec2 {
  const centroid = {
    x: (nose.x + tailA.x + tailB.x) / 3,
    y: (nose.y + tailA.y + tailB.y) / 3,
  };
  const light = lightDirection();
  return {
    x: centroid.x + light.x * PLAYER_RADIUS * CANOPY_GLINT_FRACTION,
    y: centroid.y + light.y * PLAYER_RADIUS * CANOPY_GLINT_FRACTION,
  };
}

/** The exhaust plume (player.py _draw_engine_glow): base inside the hull at
 * the tail, apex reaching ENGINE_GLOW_REACH_* past center with the throttle
 * — an idle ember at rest, full flame under thrust. Both radii stay under
 * the halo band's 25px inner edge. */
export function engineGlowGeometry(
  x: number,
  y: number,
  rotation: number,
  thrustLevel: number,
): { baseCenter: Vec2; apex: Vec2; halfWidth: number; right: Vec2 } {
  const noseDir = rotateDeg(UP, rotation);
  const reach =
    ENGINE_GLOW_REACH_IDLE_PX +
    (ENGINE_GLOW_REACH_THRUST_PX - ENGINE_GLOW_REACH_IDLE_PX) * thrustLevel;
  const halfWidth = ENGINE_GLOW_HALF_WIDTH + ENGINE_GLOW_WIDTH_GAIN * thrustLevel;
  const baseCenter = {
    x: x - noseDir.x * (PLAYER_RADIUS - ENGINE_GLOW_TAIL_INSET),
    y: y - noseDir.y * (PLAYER_RADIUS - ENGINE_GLOW_TAIL_INSET),
  };
  const apex = { x: x - noseDir.x * reach, y: y - noseDir.y * reach };
  return { baseCenter, apex, halfWidth, right: rotateDeg(UP, rotation + 90) };
}

/** The drop shadow's offset in screen space (mostly beneath the hull). */
export function shipShadowOffset(): Vec2 {
  return { x: SHIP_SHADOW_OFFSET[0], y: SHIP_SHADOW_OFFSET[1] };
}

/** The hull gradient's color for one band fraction — the deep-indigo shade
 * brightening to the hull hue (the seat's color; the desktop's lone ship is
 * seat 0, so the pair matches player.py exactly there). */
export function hullBandColor(hull: RGB, fraction: number): RGB {
  return mixColors(PALETTE.ship_hull_shade, hull, fraction);
}

/** The engine glow's backing-disc color: the flame hue melted toward the
 * paper (the no-alpha fade) so the plume reads as light, not a sticker. */
export function engineGlowBackingColor(): RGB {
  return mixColors(PALETTE.engine_glow, PALETTE.paper, 0.55);
}
