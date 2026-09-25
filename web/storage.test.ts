/**
 * Tests for the localStorage save — the desktop's corrupt-fallback
 * contract: defaults on any problem, sanitization of every field, and
 * round-trip persistence. A null storage (privacy mode) degrades to
 * defaults silently.
 */
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_SAVE, loadSave, writeSave, type SaveStorage } from "./storage";

function memoryStorage(initial: Record<string, string> = {}): SaveStorage & { map: Map<string, string> } {
  const map = new Map(Object.entries(initial));
  return {
    map,
    getItem: (key) => (map.has(key) ? (map.get(key) as string) : null),
    setItem: (key, value) => void map.set(key, value),
  };
}

describe("loadSave", () => {
  it("falls back to defaults when nothing is stored", () => {
    expect(loadSave(memoryStorage())).toEqual(DEFAULT_SAVE);
  });

  it("falls back to defaults with no storage at all", () => {
    expect(loadSave(null)).toEqual(DEFAULT_SAVE);
    expect(loadSave(undefined)).toEqual(DEFAULT_SAVE);
  });

  it("round-trips a written save", () => {
    const storage = memoryStorage();
    writeSave(storage, { highScore: 1234, muted: true, solo: { credits: 88, levels: { income: 2 }, powerupUses: { nuke: 1 } } });
    expect(loadSave(storage)).toEqual({
      highScore: 1234,
      muted: true,
      solo: { credits: 88, levels: { income: 2 }, powerupUses: { nuke: 1 } },
    });
  });

  it("sanitizes corrupt numbers, booleans, and nested junk", () => {
    const storage = memoryStorage({
      "asteroids.web-save": JSON.stringify({
        highScore: "lots",
        muted: "yes",
        solo: { credits: -5, levels: { income: "high", drone: 3 }, powerupUses: { nuke: 2.5, gold_rush: 1 } },
      }),
    });
    expect(loadSave(storage)).toEqual({
      highScore: 0,
      muted: false,
      solo: { credits: 0, levels: { drone: 3 }, powerupUses: { gold_rush: 1 } },
    });
  });

  it("warns and falls back on unparseable JSON", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const storage = memoryStorage({ "asteroids.web-save": "{not json" });
    expect(loadSave(storage)).toEqual(DEFAULT_SAVE);
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});

describe("writeSave", () => {
  it("warns instead of throwing when persistence fails", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const storage: SaveStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("quota exceeded");
      },
    };
    expect(() => writeSave(storage, DEFAULT_SAVE)).not.toThrow();
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("is a silent no-op with no storage", () => {
    expect(() => writeSave(null, DEFAULT_SAVE)).not.toThrow();
  });
});
