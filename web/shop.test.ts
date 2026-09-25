/**
 * Tests for the shop view's pure seams — cell text, affordability, price
 * escalation, the active-effects label, the clickable-strip hit test, and
 * slot→target resolution. Canvas draws are dogfood-verified.
 */
import { describe, expect, it } from "vitest";
import { POWERUPS, SHOP_LINE_STEP, SHOP_PANEL_HEIGHT, SCREEN_HEIGHT, SCREEN_WIDTH, UPGRADE_DEFS } from "../shared/constants";
import type { EconomyState } from "../shared/sim";
import { powerupPrice, upgradeCost } from "../shared/sim";
import {
  activePowerupsLabel,
  powerupCell,
  shopCell,
  shopCellAt,
  shopTargetForSlot,
} from "./shop";

function economy(overrides: Partial<EconomyState> = {}): EconomyState {
  return {
    credits: 0,
    levels: { nanoblade: 0, fire_rate: 0, income: 0, drone: 0 },
    powerupUses: {},
    powerupTimers: {},
    ...overrides,
  };
}

describe("shopCell", () => {
  it("formats title and detail like the desktop panel rows", () => {
    const def = UPGRADE_DEFS[0] as (typeof UPGRADE_DEFS)[number];
    const cell = shopCell(def, economy({ credits: 1000, levels: { nanoblade: 0, fire_rate: 2, income: 0, drone: 0 } }));
    expect(cell.title).toBe("[1] Nanoblade  Lv 0");
    expect(cell.affordable).toBe(true);
    const fireCell = shopCell(UPGRADE_DEFS[1] as (typeof UPGRADE_DEFS)[number], economy({ credits: 0, levels: { nanoblade: 0, fire_rate: 2, income: 0, drone: 0 } }));
    expect(fireCell.title).toBe("[2] Fire-rate  Lv 2");
    expect(fireCell.affordable).toBe(false);
  });

  it("prices through the shared sim's curve, never a local re-derivation", () => {
    const def = UPGRADE_DEFS[0] as (typeof UPGRADE_DEFS)[number];
    const state = economy({ levels: { nanoblade: 3, fire_rate: 0, income: 0, drone: 0 } });
    const cell = shopCell(def, state);
    expect(cell.detail).toContain(`${Math.trunc(upgradeCost(state, "nanoblade"))} cr`);
  });
});

describe("powerupCell", () => {
  it("escalates the per-use price and gates affordability", () => {
    const state = economy({ credits: 500, powerupUses: { gold_rush: 1 } });
    const cell = powerupCell("gold_rush", state);
    expect(cell.title).toContain(`[7] Gold Rush ${Math.trunc(powerupPrice(state, "gold_rush"))} cr`);
    expect(cell.affordable).toBe(true);
    const nuke = powerupCell("nuke", state);
    expect(nuke.affordable).toBe(false); // 1000 cr base > 500 credits
  });
});

describe("activePowerupsLabel", () => {
  it("returns null with no running effects", () => {
    expect(activePowerupsLabel(economy())).toBeNull();
  });

  it("lists running effects soonest-expiry-first", () => {
    const label = activePowerupsLabel(economy({ powerupTimers: { overdrive: 9.5, gold_rush: 2.21 } }));
    expect(label).toBe("Gold Rush 2.2s · Overdrive 9.5s");
  });
});

describe("shopCellAt (clickable strips)", () => {
  const upgradeTop = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT;
  const powerupTop = upgradeTop - SHOP_LINE_STEP;

  it("maps the bottom panel to upgrade slots 1–4", () => {
    expect(shopCellAt(0, upgradeTop)).toBe(1);
    expect(shopCellAt(SCREEN_WIDTH / 2, SCREEN_HEIGHT - 1)).toBe(3);
    expect(shopCellAt(SCREEN_WIDTH - 1, upgradeTop)).toBe(4);
  });

  it("maps the powerup strip to slots 7–0", () => {
    expect(shopCellAt(0, powerupTop)).toBe(7);
    expect(shopCellAt(SCREEN_WIDTH / 2, powerupTop)).toBe(9);
    expect(shopCellAt(SCREEN_WIDTH - 1, powerupTop)).toBe(0);
  });

  it("returns null above the strips — that's click-to-chip territory", () => {
    expect(shopCellAt(SCREEN_WIDTH / 2, powerupTop - 1)).toBeNull();
    expect(shopCellAt(SCREEN_WIDTH / 2, 0)).toBeNull();
  });
});

describe("shopTargetForSlot", () => {
  it("sends upgrades and powerups to the right handlers", () => {
    expect(shopTargetForSlot(1)).toEqual({ kind: "upgrade", name: "nanoblade", slot: 1 });
    expect(shopTargetForSlot(4)).toEqual({ kind: "upgrade", name: "drone", slot: 4 });
    expect(shopTargetForSlot(7)).toEqual({ kind: "powerup", name: "gold_rush", slot: 7 });
    expect(shopTargetForSlot(8)).toEqual({ kind: "powerup", name: "nuke", slot: 8 });
    expect(shopTargetForSlot(9)).toEqual({ kind: "powerup", name: "overdrive", slot: 9 });
    expect(shopTargetForSlot(0)).toEqual({ kind: "powerup", name: "chrono", slot: 0 });
  });

  it("keys every slot from the tables, not a hand-written list", () => {
    for (const def of UPGRADE_DEFS) {
      expect(shopTargetForSlot(Number(def.key) as 1 | 2 | 3 | 4)?.kind).toBe("upgrade");
    }
    for (const def of Object.values(POWERUPS)) {
      const slot = Number(def.key) as 7 | 8 | 9 | 0;
      expect(shopTargetForSlot(slot)?.kind).toBe("powerup");
    }
  });
});
