/**
 * Input capture — the browser half of pygame.key.get_pressed(). Held keys
 * resolve into a Controls struct (sent at tick rate); discrete presses
 * (shop slots, mute, restart) fire hooks. The key→meaning tables are pure
 * and unit-tested; the listener wiring is thin glue verified by dogfood.
 */
import type { Controls, ShopSlot } from "../shared/protocol";

/** Movement/shoot codes: WASD plus arrows, matching the desktop's dual
 * key sets. `back` (S) is part of the protocol Controls. */
const CONTROL_KEYS: ReadonlyArray<[keyof Controls, readonly string[]]> = [
  ["thrust", ["KeyW", "ArrowUp"]],
  ["back", ["KeyS", "ArrowDown"]],
  ["left", ["KeyA", "ArrowLeft"]],
  ["right", ["KeyD", "ArrowRight"]],
  ["shoot", ["Space"]],
];

const GAME_KEY_CODES: ReadonlySet<string> = new Set(CONTROL_KEYS.flatMap(([, codes]) => codes));

/** Keys whose default (page scroll) must be suppressed while playing. */
export const SCROLL_KEYS: ReadonlySet<string> = new Set([
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Space",
]);

/** Pure held-keys → Controls. Multiple bindings for one control OR together. */
export function controlsFromKeys(keys: ReadonlySet<string>): Controls {
  const out = { thrust: false, back: false, left: false, right: false, shoot: false };
  for (const [field, codes] of CONTROL_KEYS) {
    out[field] = codes.some((code) => keys.has(code));
  }
  return out;
}

/** Shop slots from physical keys: 1–4 buy upgrades, 7–0 fire bought
 * powerups — the desktop's key map, digits row and numpad both. */
const SLOT_CODES: ReadonlyArray<readonly [string, ShopSlot]> = [
  ["Digit1", 1],
  ["Digit2", 2],
  ["Digit3", 3],
  ["Digit4", 4],
  ["Digit7", 7],
  ["Digit8", 8],
  ["Digit9", 9],
  ["Digit0", 0],
  ["Numpad1", 1],
  ["Numpad2", 2],
  ["Numpad3", 3],
  ["Numpad4", 4],
  ["Numpad7", 7],
  ["Numpad8", 8],
  ["Numpad9", 9],
  ["Numpad0", 0],
];

const SLOT_BY_CODE: ReadonlyMap<string, ShopSlot> = new Map(SLOT_CODES);

/** Pure code → shop slot, or null when the key is not a shop key. */
export function slotFromCode(code: string): ShopSlot | null {
  return SLOT_BY_CODE.get(code) ?? null;
}

export interface InputHooks {
  onSlot(slot: ShopSlot): void;
  onToggleMute(): void;
  onRestart(): void;
}

/** Owns the keydown/keyup listeners for one page. Feed `controls()` to the
 * connection (rooms) or the sim (solo) every tick; hooks fire on presses. */
export class InputCapture {
  private readonly pressed = new Set<string>();

  constructor(private readonly hooks: InputHooks) {}

  controls(): Controls {
    return controlsFromKeys(this.pressed);
  }

  /** Drop all held keys — on window blur, so a focus loss can't stick
   * thrust on. */
  clear(): void {
    this.pressed.clear();
  }

  private readonly handleKeyDown = (event: KeyboardEvent): void => {
    if (SCROLL_KEYS.has(event.code)) event.preventDefault();
    if (event.repeat) return;
    this.pressed.add(event.code);
    const slot = slotFromCode(event.code);
    if (slot !== null) {
      this.hooks.onSlot(slot);
      return;
    }
    if (event.code === "KeyM") this.hooks.onToggleMute();
    else if (event.code === "KeyR") this.hooks.onRestart();
  };

  private readonly handleKeyUp = (event: KeyboardEvent): void => {
    this.pressed.delete(event.code);
  };

  attach(target: Pick<Window, "addEventListener" | "removeEventListener">): void {
    target.addEventListener("keydown", this.handleKeyDown);
    target.addEventListener("keyup", this.handleKeyUp);
  }

  detach(target: Pick<Window, "addEventListener" | "removeEventListener">): void {
    target.removeEventListener("keydown", this.handleKeyDown);
    target.removeEventListener("keyup", this.handleKeyUp);
    this.clear();
  }
}

/** True when the code maps to a game key (used to gate preventDefault). */
export function isGameKey(code: string): boolean {
  return GAME_KEY_CODES.has(code);
}
