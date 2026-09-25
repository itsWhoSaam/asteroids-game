/**
 * The shop view — web port of shop.py's panel rendering. The desktop's
 * purchase seams (upgrade_cost, powerup_price) live in the shared sim;
 * this module renders their state and maps clicks/keys to ShopSlot
 * intents. Buying itself is always the sim's or the server's call — the
 * client only displays and requests.
 */
import {
  POWERUP_ACTIVE_COLOR,
  POWERUPS,
  SCREEN_HEIGHT,
  SCREEN_WIDTH,
  SHOP_BRIGHT_COLOR,
  SHOP_CELL_PADDING,
  SHOP_DIM_COLOR,
  SHOP_FONT_SIZE,
  SHOP_LINE_STEP,
  SHOP_PANEL_BG,
  SHOP_PANEL_BORDER,
  SHOP_PANEL_HEIGHT,
  UPGRADE_DEFS,
} from "../shared/constants";
import type { BoughtPowerUpName, RGB, UpgradeDef, UpgradeName } from "../shared/constants";
import type { EconomyState } from "../shared/sim";
import type { ShopSlot } from "../shared/protocol";
import { powerupPrice, upgradeCost } from "../shared/sim";
import { fontCss } from "./fonts";
import { rgbCss } from "./fx";

/** One shop cell's displayed state: two text rows plus affordability. */
export interface ShopCell {
  title: string;
  detail: string;
  affordable: boolean;
}

function affordabilityColor(affordable: boolean): RGB {
  return affordable ? SHOP_BRIGHT_COLOR : SHOP_DIM_COLOR;
}

function cellWidth(): number {
  return SCREEN_WIDTH / UPGRADE_DEFS.length;
}

/** The `[key] Title  Lv n` / `cost cr · effect` pair for one upgrade. */
export function shopCell(def: UpgradeDef, economy: EconomyState): ShopCell {
  const level = economy.levels[def.name];
  const cost = upgradeCost(economy, def.name);
  return {
    title: `[${def.key}] ${def.title}  Lv ${level}`,
    detail: `${Math.trunc(cost)} cr · ${def.effect}`,
    affordable: economy.credits >= cost,
  };
}

/** The `[key] Title price cr · desc` strip cell for one bought powerup —
 * a single row, as on the desktop. */
export function powerupCell(name: BoughtPowerUpName, economy: EconomyState): ShopCell {
  const def = POWERUPS[name];
  const price = powerupPrice(economy, name);
  return {
    title: `[${def.key}] ${def.title} ${Math.trunc(price)} cr · ${def.desc}`,
    detail: "",
    affordable: economy.credits >= price,
  };
}

/** Running timed effects, soonest expiry first — "Title 5.3s · …", or
 * null when the ledger has no active clock (the desktop's active line). */
export function activePowerupsLabel(economy: EconomyState): string | null {
  const actives = (Object.keys(POWERUPS) as BoughtPowerUpName[])
    .filter((name) => economy.powerupTimers[name] !== undefined)
    .map((name) => ({ name, remaining: economy.powerupTimers[name] as number }))
    .sort((a, b) => a.remaining - b.remaining);
  if (actives.length === 0) return null;
  return actives
    .map(({ name, remaining }) => `${POWERUPS[name].title} ${remaining.toFixed(1)}s`)
    .join(" · ");
}

const UPGRADE_SLOTS: readonly ShopSlot[] = [1, 2, 3, 4];
const POWERUP_SLOTS: readonly ShopSlot[] = [7, 8, 9, 0];

/** The digit a ShopSlot prints as — the protocol's key binding, 0 aside. */
export function slotKeyLabel(slot: ShopSlot): string {
  return String(slot);
}

/**
 * Hit-test for the clickable shop: a point in the upgrade strip buys its
 * cell (slots 1–4), a point in the powerup strip fires that powerup
 * (7–0). Anything else is click-to-chip — null here.
 */
export function shopCellAt(x: number, y: number): ShopSlot | null {
  const upgradeTop = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT;
  if (y >= upgradeTop) {
    const index = Math.floor(x / cellWidth());
    return UPGRADE_SLOTS[index] ?? null;
  }
  const powerupTop = upgradeTop - SHOP_LINE_STEP;
  if (y >= powerupTop) {
    const index = Math.floor(x / cellWidth());
    return POWERUP_SLOTS[index] ?? null;
  }
  return null;
}

/** The bottom panel: one cell per upgrade, affordability as brightness
 * (draw_panel). Values read the live ledger through the shared sim's
 * price seams. */
export function drawShopPanel(ctx: CanvasRenderingContext2D, economy: EconomyState): void {
  const top = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT;
  ctx.fillStyle = rgbCss(SHOP_PANEL_BG);
  ctx.fillRect(0, top, SCREEN_WIDTH, SHOP_PANEL_HEIGHT);
  ctx.strokeStyle = rgbCss(SHOP_PANEL_BORDER);
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, top);
  ctx.lineTo(SCREEN_WIDTH, top);
  ctx.stroke();

  ctx.font = fontCss(SHOP_FONT_SIZE);
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  UPGRADE_DEFS.forEach((def, index) => {
    const cell = shopCell(def, economy);
    ctx.fillStyle = rgbCss(affordabilityColor(cell.affordable));
    const x = index * cellWidth() + SHOP_CELL_PADDING;
    ctx.fillText(cell.title, x, top + SHOP_CELL_PADDING);
    ctx.fillText(cell.detail, x, top + SHOP_CELL_PADDING + SHOP_LINE_STEP);
  });
}

/** The powerup strip one line above the panel, plus the active-effects
 * countdown above it (draw_powerups). */
export function drawShopPowerups(ctx: CanvasRenderingContext2D, economy: EconomyState): void {
  const panelTop = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT;
  ctx.font = fontCss(SHOP_FONT_SIZE);
  ctx.textAlign = "left";
  ctx.textBaseline = "top";

  const activeLabel = activePowerupsLabel(economy);
  if (activeLabel !== null) {
    ctx.fillStyle = rgbCss(POWERUP_ACTIVE_COLOR);
    ctx.fillText(activeLabel, SHOP_CELL_PADDING, panelTop - 2 * SHOP_LINE_STEP);
  }

  (Object.keys(POWERUPS) as BoughtPowerUpName[]).forEach((name, index) => {
    const cell = powerupCell(name, economy);
    ctx.fillStyle = rgbCss(affordabilityColor(cell.affordable));
    ctx.fillText(cell.title, SHOP_CELL_PADDING + index * cellWidth(), panelTop - SHOP_LINE_STEP);
  });
}

/** The upgrade a slot buys, or null for the powerup slots. */
export function upgradeForSlot(slot: ShopSlot): UpgradeDef | null {
  return UPGRADE_DEFS.find((def) => def.key === slotKeyLabel(slot)) ?? null;
}

/** The powerup a slot fires, or null for the upgrade slots. */
export function powerupForSlot(slot: ShopSlot): BoughtPowerUpName | null {
  const entry = (Object.entries(POWERUPS) as Array<[BoughtPowerUpName, { key: string }]>).find(
    ([, def]) => def.key === slotKeyLabel(slot),
  );
  return entry ? entry[0] : null;
}

export type ShopTarget =
  | { kind: "upgrade"; name: UpgradeName; slot: ShopSlot }
  | { kind: "powerup"; name: BoughtPowerUpName; slot: ShopSlot };

/** Resolve a slot to its shop target (upgrade or powerup), or null. */
export function shopTargetForSlot(slot: ShopSlot): ShopTarget | null {
  const upgrade = upgradeForSlot(slot);
  if (upgrade) return { kind: "upgrade", name: upgrade.name, slot };
  const powerup = powerupForSlot(slot);
  if (powerup) return { kind: "powerup", name: powerup, slot };
  return null;
}
