/**
 * Tests for the pure input tables — key codes → Controls, shop slots, and
 * the scroll-suppression set. The listener glue (InputCapture) is thin
 * browser wiring verified by dogfood, not unit tests.
 */
import { describe, expect, it } from "vitest";
import { SCROLL_KEYS, controlsFromKeys, isGameKey, slotFromCode } from "./input";

describe("controlsFromKeys", () => {
  it("maps WASD + Space to the Controls struct", () => {
    const keys = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "Space"]);
    expect(controlsFromKeys(keys)).toEqual({ thrust: true, back: true, left: true, right: true, shoot: true });
  });

  it("maps the arrow alternatives too", () => {
    const keys = new Set(["ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"]);
    expect(controlsFromKeys(keys)).toEqual({ thrust: true, back: true, left: true, right: true, shoot: false });
  });

  it("returns all-false for an empty set", () => {
    expect(controlsFromKeys(new Set())).toEqual({ thrust: false, back: false, left: false, right: false, shoot: false });
  });

  it("ands dual bindings (either binding holds the control)", () => {
    expect(controlsFromKeys(new Set(["KeyW", "ArrowLeft"])).thrust).toBe(true);
    expect(controlsFromKeys(new Set(["KeyW", "ArrowLeft"])).left).toBe(true);
    expect(controlsFromKeys(new Set(["KeyW", "ArrowLeft"])).shoot).toBe(false);
  });
});

describe("slotFromCode", () => {
  it("maps the desktop shop slots on the digits row", () => {
    expect(slotFromCode("Digit1")).toBe(1);
    expect(slotFromCode("Digit2")).toBe(2);
    expect(slotFromCode("Digit3")).toBe(3);
    expect(slotFromCode("Digit4")).toBe(4);
    expect(slotFromCode("Digit7")).toBe(7);
    expect(slotFromCode("Digit8")).toBe(8);
    expect(slotFromCode("Digit9")).toBe(9);
    expect(slotFromCode("Digit0")).toBe(0);
  });

  it("accepts the numpad mirrors", () => {
    expect(slotFromCode("Numpad4")).toBe(4);
    expect(slotFromCode("Numpad0")).toBe(0);
  });

  it("is null for non-shop keys (including unmapped digits)", () => {
    expect(slotFromCode("KeyM")).toBeNull();
    expect(slotFromCode("Digit5")).toBeNull(); // 5/6 are not shop slots
    expect(slotFromCode("Numpad5")).toBeNull();
    expect(slotFromCode("Digit6")).toBeNull();
  });
});

describe("scroll suppression", () => {
  it("covers exactly the keys that scroll a page", () => {
    for (const code of ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"]) {
      expect(SCROLL_KEYS.has(code)).toBe(true);
    }
    expect(SCROLL_KEYS.has("KeyW")).toBe(false);
  });

  it("flags movement codes as game keys", () => {
    expect(isGameKey("KeyW")).toBe(true);
    expect(isGameKey("Space")).toBe(true);
    expect(isGameKey("KeyM")).toBe(false); // M/R are hooks, not held controls
  });
});
