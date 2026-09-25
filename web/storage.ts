/**
 * localStorage persistence — the web twin of hud.py's game_save.json
 * loader. Same contract: missing or corrupt data falls back to defaults,
 * never a crash; a failed write warns instead of throwing. The browser
 * save owns the high score, the mute preference, and the solo mode's
 * credits/levels (the spec replaces game_save.json with localStorage).
 */
import type { BoughtPowerUpName, UpgradeName } from "../shared/constants";

const SAVE_KEY = "asteroids.web-save";

/** What solo mode persists across sessions; rooms never write here. */
export interface SoloSave {
  credits: number;
  levels: Partial<Record<UpgradeName, number>>;
  powerupUses: Partial<Record<BoughtPowerUpName, number>>;
}

export interface WebSave {
  highScore: number;
  muted: boolean;
  solo: SoloSave;
}

export const DEFAULT_SAVE: WebSave = {
  highScore: 0,
  muted: false,
  solo: { credits: 0, levels: {}, powerupUses: {} },
};

export interface SaveStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function nonNegativeInt(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function sanitizeSolo(raw: unknown): SoloSave {
  const fallback: SoloSave = { credits: 0, levels: {}, powerupUses: {} };
  if (typeof raw !== "object" || raw === null) return fallback;
  const source = raw as Record<string, unknown>;
  const credits = nonNegativeInt(source.credits);
  const levels: SoloSave["levels"] = {};
  if (typeof source.levels === "object" && source.levels !== null) {
    for (const [name, value] of Object.entries(source.levels as Record<string, unknown>)) {
      const level = nonNegativeInt(value);
      if (level !== null) levels[name as UpgradeName] = level;
    }
  }
  const powerupUses: SoloSave["powerupUses"] = {};
  if (typeof source.powerupUses === "object" && source.powerupUses !== null) {
    for (const [name, value] of Object.entries(source.powerupUses as Record<string, unknown>)) {
      const uses = nonNegativeInt(value);
      if (uses !== null) powerupUses[name as BoughtPowerUpName] = uses;
    }
  }
  return { credits: credits ?? 0, levels, powerupUses };
}

/** Load and validate the save; any problem yields defaults, never a throw. */
export function loadSave(storage: SaveStorage | null | undefined): WebSave {
  if (!storage) return { ...DEFAULT_SAVE, solo: { ...DEFAULT_SAVE.solo } };
  try {
    const raw = storage.getItem(SAVE_KEY);
    if (typeof raw !== "string" || raw === "") return { ...DEFAULT_SAVE, solo: { ...DEFAULT_SAVE.solo } };
    const data: unknown = JSON.parse(raw);
    if (typeof data !== "object" || data === null) {
      return { ...DEFAULT_SAVE, solo: { ...DEFAULT_SAVE.solo } };
    }
    const source = data as Record<string, unknown>;
    const highScore = nonNegativeInt(source.highScore) ?? 0;
    const muted = typeof source.muted === "boolean" ? source.muted : false;
    return { highScore, muted, solo: sanitizeSolo(source.solo) };
  } catch (error) {
    console.warn(`asteroids: [save] warning: corrupt save ignored: ${String(error)}`);
    return { ...DEFAULT_SAVE, solo: { ...DEFAULT_SAVE.solo } };
  }
}

/** Persist the save; failure warns like the desktop's write_save. */
export function writeSave(storage: SaveStorage | null | undefined, save: WebSave): void {
  if (!storage) return;
  try {
    storage.setItem(SAVE_KEY, JSON.stringify(save));
  } catch (error) {
    console.warn(`asteroids: [save] warning: could not persist save: ${String(error)}`);
  }
}
