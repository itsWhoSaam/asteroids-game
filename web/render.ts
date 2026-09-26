/**
 * The Canvas 2D world renderer — the client's answer to the desktop
 * build's draw code. Entity looks port 1:1 from the pygame sources
 * (player.py / asteroid.py / shot.py / powerups.py / drones.py draws and
 * comicfx.py's ink stack); the background overlay ports build_background
 * (visual V3). Pixels need not be identical to SDL's — physics and feel do.
 */
import {
  ASTEROID_KINDS,
  ASTEROID_MIN_RADIUS,
  BANK_FRACTION,
  CANOPY_GLINT_RADIUS,
  DRONE_MARKER_COLOR,
  DRONE_MARKER_RADIUS,
  DRONE_ORBIT_RADIUS,
  HULL_GRADIENT_BANDS,
  LINE_WIDTH,
  PALETTE,
  PLAYER_BLINK_HZ,
  PLAYER_RADIUS,
  POWERUP_RADIUS,
  POWERUP_SHIELD_RING_GAP,
  SCREEN_HEIGHT,
  SCREEN_WIDTH,
  SHOT_RADIUS,
} from "../shared/constants";
import type { RGB } from "../shared/constants";
import { rotateDeg } from "../shared/sim";
import type { AsteroidSnap, PlayerSnap, Snapshot } from "../shared/protocol";
import type { PowerUpKind } from "../shared/constants";
import { fontCss } from "./fonts";
import type { FloatingTexts, ParticleField } from "./fx";
import { rgbCss } from "./fx";
import {
  canopyGlintCenter,
  canopyPoints,
  engineGlowBackingColor,
  engineGlowGeometry,
  fillPolygon,
  getRockBake,
  hullBandColor,
  hullGradientBands,
  pruneShipClocks,
  rockInkPoints,
  shipShadowOffset,
  spinAngleFor,
  updateShipClocks,
} from "./sem3d";

const UP = { x: 0, y: 1 };

// comicfx.py's chromatic pair — the sim's constants mirror doesn't carry
// presentation-only palette keys, but the values live in constants.py:62-63.
const INK: RGB = [0, 0, 0];
const FRINGE_PX = 2;
const HALFTONE_COLOR: RGB = [62, 51, 140]; // constants.py: "halftone"
const ACTION_LINE_COLOR: RGB = [40, 32, 94]; // constants.py: "action_line"
const HALFTONE_SPACING = 12;
const HALFTONE_DOT_RADIUS = 2;
const ACTION_LINE_COUNT = 24;
const ACTION_LINE_INNER_RADIUS = 150;
const BACKGROUND_ALPHA = 56 / 255; // 56/255 ≈ 22% — comicfx.py BACKGROUND_ALPHA

const ASTEROID_COLOR_KEYS = ["asteroid_s", "asteroid_m", "asteroid_l"] as const;

/** Pure palette hue for a rock, by size tier — asteroid.asteroid_color. */
export function asteroidColor(radius: number): RGB {
  const tier = Math.min(ASTEROID_KINDS, Math.max(1, Math.round(radius / ASTEROID_MIN_RADIUS)));
  const key = ASTEROID_COLOR_KEYS[tier - 1];
  return PALETTE[key === undefined ? "asteroid_s" : key];
}

/** One hull color per player, stable for the seat: sorted by player id, so
 * colors survive any snapshot order. Seat 0 keeps the desktop cyan. */
export function assignShipColors(players: PlayerSnap[]): Record<string, RGB> {
  const cycle: readonly RGB[] = [
    PALETTE.ship,
    PALETTE.powerup_triple,
    PALETTE.powerup_rapid,
    PALETTE.asteroid_l,
  ];
  const colors: Record<string, RGB> = {};
  [...players]
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .forEach((p, index) => {
      colors[p.id] = cycle[index % cycle.length] ?? PALETTE.ship;
    });
  return colors;
}

/** player.py's triangle(): tip on the nose, base behind — the same rotateDeg
 * the sim moves by, so the ship renders exactly where the desktop's does.
 * bank (semi-3D): -1..1 from the presentation clock — the wing offsets scale
 * by ±BANK_FRACTION so the ship leans into turns; bank=0 is the pinned
 * plan every existing caller and test knows. */
export function shipTriangle(
  x: number,
  y: number,
  rotation: number,
  bank = 0,
): Array<{ x: number; y: number }> {
  const forward = rotateDeg(UP, rotation);
  const right = rotateDeg(UP, rotation + 90);
  const rx = (right.x * PLAYER_RADIUS) / 1.5;
  const ry = (right.y * PLAYER_RADIUS) / 1.5;
  return [
    { x: x + forward.x * PLAYER_RADIUS, y: y + forward.y * PLAYER_RADIUS },
    {
      x: x - forward.x * PLAYER_RADIUS - rx * (1 - BANK_FRACTION * bank),
      y: y - forward.y * PLAYER_RADIUS - ry * (1 - BANK_FRACTION * bank),
    },
    {
      x: x - forward.x * PLAYER_RADIUS + rx * (1 + BANK_FRACTION * bank),
      y: y - forward.y * PLAYER_RADIUS + ry * (1 + BANK_FRACTION * bank),
    },
  ];
}

/** comicfx.chromatic_circle: black ink, offset red/cyan fringes, colored
 * stroke — three passes, cheapest color last. */
export function chromaticCircle(
  ctx: CanvasRenderingContext2D,
  color: RGB,
  x: number,
  y: number,
  radius: number,
  width = LINE_WIDTH,
): void {
  ctx.strokeStyle = rgbCss(INK);
  ctx.lineWidth = width + FRINGE_PX;
  ctx.beginPath();
  ctx.arc(x, y, radius + width, 0, Math.PI * 2);
  ctx.stroke();
  for (const [dx, fringe] of [
    [-FRINGE_PX, PALETTE.fringe_r],
    [FRINGE_PX, PALETTE.fringe_c],
  ] as const) {
    ctx.strokeStyle = rgbCss(fringe);
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.arc(x + dx, y, radius, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.strokeStyle = rgbCss(color);
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.stroke();
}

/** comicfx.chromatic_polygon — the same three-pass stack for the hull. */
export function chromaticPolygon(
  ctx: CanvasRenderingContext2D,
  color: RGB,
  points: Array<{ x: number; y: number }>,
  width = LINE_WIDTH,
): void {
  const trace = (dx: number): void => {
    ctx.beginPath();
    points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x + dx, p.y) : ctx.lineTo(p.x + dx, p.y)));
    ctx.closePath();
  };
  ctx.strokeStyle = rgbCss(INK);
  ctx.lineWidth = width + FRINGE_PX;
  trace(0);
  ctx.stroke();
  for (const [dx, fringe] of [
    [-FRINGE_PX, PALETTE.fringe_r],
    [FRINGE_PX, PALETTE.fringe_c],
  ] as const) {
    ctx.strokeStyle = rgbCss(fringe);
    ctx.lineWidth = width;
    trace(dx);
    ctx.stroke();
  }
  ctx.strokeStyle = rgbCss(color);
  ctx.lineWidth = width;
  trace(0);
  ctx.stroke();
}

/** comicfx.build_background: paper, radial action lines, hex-packed halftone
 * dot grid — pure arithmetic, pre-rendered once. The caller composites it
 * at BACKGROUND_ALPHA, screen-level: over the shaken world, under the HUD. */
export function buildBackground(width: number, height: number): HTMLCanvasElement {
  const overlay = document.createElement("canvas");
  overlay.width = width;
  overlay.height = height;
  const ctx = overlay.getContext("2d");
  if (!ctx) return overlay;
  ctx.fillStyle = rgbCss(PALETTE.paper);
  ctx.fillRect(0, 0, width, height);

  const centerX = width / 2;
  const centerY = height / 2;
  const reach = Math.sqrt(width ** 2 + height ** 2);
  ctx.strokeStyle = rgbCss(ACTION_LINE_COLOR);
  for (let i = 0; i < ACTION_LINE_COUNT; i += 1) {
    const angle = (i * 360) / ACTION_LINE_COUNT;
    const dir = rotateDeg({ x: 1, y: 0 }, angle);
    ctx.lineWidth = i % 4 === 0 ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(centerX + dir.x * ACTION_LINE_INNER_RADIUS, centerY + dir.y * ACTION_LINE_INNER_RADIUS);
    ctx.lineTo(centerX + dir.x * reach, centerY + dir.y * reach);
    ctx.stroke();
  }

  ctx.fillStyle = rgbCss(HALFTONE_COLOR);
  const rows = Math.floor(height / HALFTONE_SPACING) + 1;
  const cols = Math.floor(width / HALFTONE_SPACING) + 1;
  for (let row = 0; row < rows; row += 1) {
    const y = row * HALFTONE_SPACING;
    const xOffset = (row % 2) * (HALFTONE_SPACING / 2);
    for (let col = 0; col < cols; col += 1) {
      ctx.beginPath();
      ctx.arc(col * HALFTONE_SPACING + xOffset, y, HALFTONE_DOT_RADIUS, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  return overlay;
}

export interface WorldView {
  snap: Snapshot;
  shipColors: Record<string, RGB>;
  showNameTags: boolean;
  particles: ParticleField;
  floats: FloatingTexts;
  /** Presentation clock (seconds — the rAF time the caller renders at):
   * drives asteroid tumble and the ship's bank/throttle easing. Never sim
   * state; the sim's dt gates live server-side. */
  now: number;
}

function powerupColor(kind: PowerUpKind): RGB {
  switch (kind) {
    case "shield":
      return PALETTE.powerup_shield;
    case "rapid":
      return PALETTE.powerup_rapid;
    default:
      return PALETTE.powerup_triple;
  }
}

function drawDrones(ctx: CanvasRenderingContext2D, snap: Snapshot): void {
  for (const turret of snap.drones) {
    const anchor = snap.players.find((p) => p.id === turret.anchorId);
    if (!anchor) continue;
    const offset = rotateDeg(UP, turret.orbitAngle);
    const mx = anchor.x + offset.x * DRONE_ORBIT_RADIUS;
    const my = anchor.y + offset.y * DRONE_ORBIT_RADIUS;
    ctx.strokeStyle = rgbCss(DRONE_MARKER_COLOR);
    ctx.lineWidth = LINE_WIDTH;
    ctx.beginPath();
    ctx.arc(mx, my, DRONE_MARKER_RADIUS, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawPlayer(ctx: CanvasRenderingContext2D, p: PlayerSnap, view: WorldView): void {
  if (p.lives <= 0) return; // out of lives = no ship (spectating)
  // Presentation clocks ease every visible frame (player.py eases in
  // update(), not draw()): bank leans into the turn, throttle drives the
  // exhaust plume. Never read by the sim.
  const { bank, thrust } = updateShipClocks(p, view.now);
  // Grace-window blink: skip the draw on alternate half-cycles.
  const blinkDark = p.invulnTimer > 0 && (p.invulnTimer * PLAYER_BLINK_HZ) % 1 >= 0.5;
  const hull = view.shipColors[p.id] ?? PALETTE.ship;
  if (!blinkDark) {
    const points = shipTriangle(p.x, p.y, p.rotation, bank);
    // Soft drop shadow (semi-3D): the hull's own shape offset in screen
    // space — the hull covers all but the offset sliver, sitting the ship
    // off the paper. Tuned (with the glow below) to stay inside the halo
    // tripwire band's 25px inner edge.
    const shadow = shipShadowOffset();
    fillPolygon(
      ctx,
      points.map((pt) => ({ x: pt.x + shadow.x, y: pt.y + shadow.y })),
      PALETTE.ship_drop_shadow,
    );
    // Gradient hull (semi-3D): the banded nose→tail cel fill — the
    // deep-indigo shade at the tail brightening to the hull hue at the
    // nose, hard band edges like the rocks' shading.
    const [nose, tailA, tailB] = points;
    if (nose && tailA && tailB) {
      for (const { quad, fraction } of hullGradientBands(nose, tailA, tailB, HULL_GRADIENT_BANDS)) {
        fillPolygon(ctx, quad, hullBandColor(hull, fraction));
      }
      // Canopy (semi-3D): a small dome at the hull's centroid with the
      // specular glint dot toward the shared light — the strongest 3D cue
      // at this scale.
      fillPolygon(ctx, canopyPoints(nose, tailA, tailB, p.rotation), PALETTE.ship_canopy);
      const glint = canopyGlintCenter(nose, tailA, tailB);
      ctx.beginPath();
      ctx.arc(glint.x, glint.y, CANOPY_GLINT_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = rgbCss(PALETTE.hud_ink);
      ctx.fill();
    }
    // Inked comic hull (V2): black ink, chromatic fringes, hull stroke —
    // unchanged, now tracing the banked hull over its fill.
    chromaticPolygon(ctx, hull, points);
    // Engine glow (semi-3D): the exhaust plume over the tail — drawn after
    // the ink stack so the idle ember stays readable past the tail ink;
    // its reach is tuned (with the shadow offset) to keep the halo tripwire
    // band paper.
    const glow = engineGlowGeometry(p.x, p.y, p.rotation, thrust);
    ctx.beginPath();
    ctx.arc(
      glow.baseCenter.x,
      glow.baseCenter.y,
      Math.max(1, Math.floor(glow.halfWidth + 2)),
      0,
      Math.PI * 2,
    );
    ctx.fillStyle = rgbCss(engineGlowBackingColor());
    ctx.fill();
    fillPolygon(
      ctx,
      [
        {
          x: glow.baseCenter.x + glow.right.x * glow.halfWidth,
          y: glow.baseCenter.y + glow.right.y * glow.halfWidth,
        },
        {
          x: glow.baseCenter.x - glow.right.x * glow.halfWidth,
          y: glow.baseCenter.y - glow.right.y * glow.halfWidth,
        },
        { x: glow.apex.x, y: glow.apex.y },
      ],
      PALETTE.engine_glow,
    );
    // Shield ring (F4): a stocked charge shows outside the hull, so the
    // player can see the next hit will be absorbed. Blinking with the
    // ship above keeps the ring honest during the grace window too.
    if (p.shieldHits > 0) {
      chromaticCircle(ctx, PALETTE.powerup_shield, p.x, p.y, PLAYER_RADIUS + POWERUP_SHIELD_RING_GAP);
    }
  }
  if (view.showNameTags) {
    // Room identity: name plus remaining lives, in the hull's hue.
    ctx.fillStyle = rgbCss(hull);
    ctx.font = fontCss(14, 700);
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText(`${p.name} ×${p.lives}`, p.x, p.y - PLAYER_RADIUS - 6);
  }
}

/** asteroid.py's draw: the shaded body — tier-hue fill, two-band shadow
 * crescent, highlight arc, seeded craters — bakes once per rock and
 * rotates at draw time (canvas rotate(+spin·rad) and rotateDeg(+spin)
 * share the y-down clockwise-positive convention, so bake and ink tumble
 * in lockstep); the ink stack traces the rotated lumpy silhouette,
 * keeping the black outline and red/cyan fringes on every frame. */
function drawAsteroid(ctx: CanvasRenderingContext2D, a: AsteroidSnap, now: number): void {
  const spin = spinAngleFor(a.id, now);
  const bake = getRockBake(a.id, a.radius);
  if (bake) {
    const half = bake.width / 2;
    ctx.save();
    ctx.translate(a.x, a.y);
    ctx.rotate((spin * Math.PI) / 180);
    ctx.drawImage(bake, -half, -half);
    ctx.restore();
  }
  chromaticPolygon(ctx, asteroidColor(a.radius), rockInkPoints(a, spin));
}

/** One world layer: paper fill, entities shaken at the draw origin only,
 * then the screen-level background print. HUD/shop/banners draw after,
 * unshaken — the desktop composition exactly. */
export function drawWorldLayer(
  ctx: CanvasRenderingContext2D,
  view: WorldView,
  background: HTMLCanvasElement,
  shakeDx: number,
  shakeDy: number,
): void {
  const { snap } = view;
  ctx.fillStyle = rgbCss(PALETTE.paper);
  ctx.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT);

  ctx.save();
  ctx.translate(shakeDx, shakeDy);

  for (const a of snap.asteroids) {
    drawAsteroid(ctx, a, view.now);
  }
  for (const pu of snap.powerups) {
    // The kind's identity color rings the pickup and stamps its initial —
    // powerups.py's draw.
    const color = powerupColor(pu.kind);
    chromaticCircle(ctx, color, pu.x, pu.y, POWERUP_RADIUS);
    ctx.fillStyle = rgbCss(color);
    ctx.font = fontCss(20, 700);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(pu.kind.charAt(0).toUpperCase(), pu.x, pu.y);
  }
  for (const s of snap.shots) {
    chromaticCircle(ctx, PALETTE.shot, s.x, s.y, SHOT_RADIUS);
  }
  drawDrones(ctx, snap);
  view.particles.draw(ctx);
  for (const p of snap.players) {
    drawPlayer(ctx, p, view);
  }
  pruneShipClocks(snap.players.map((p) => p.id));
  view.floats.draw(ctx);

  ctx.restore();

  // The print texture sits over the shaken world and under the HUD —
  // screen-level, so it never scrolls or shakes.
  ctx.globalAlpha = BACKGROUND_ALPHA;
  ctx.drawImage(background, 0, 0);
  ctx.globalAlpha = 1;
}

/** Letterbox scaling for the fixed 1280×720 logical resolution. */
export function fitCanvasToWindow(canvas: HTMLCanvasElement): void {
  const scale = Math.min(window.innerWidth / SCREEN_WIDTH, window.innerHeight / SCREEN_HEIGHT);
  canvas.style.width = `${Math.floor(SCREEN_WIDTH * scale)}px`;
  canvas.style.height = `${Math.floor(SCREEN_HEIGHT * scale)}px`;
}

/** Page coordinates → logical canvas coordinates (1280×720 space). */
export function canvasPoint(canvas: HTMLCanvasElement, clientX: number, clientY: number): { x: number; y: number } {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((clientX - rect.left) * SCREEN_WIDTH) / rect.width,
    y: ((clientY - rect.top) * SCREEN_HEIGHT) / rect.height,
  };
}

export { SCREEN_HEIGHT, SCREEN_WIDTH };
