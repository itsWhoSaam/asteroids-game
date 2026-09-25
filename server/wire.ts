/**
 * Runtime validation of the wire vocabulary. Everything that arrives on a
 * WebSocket is untrusted: this module is the single gate that turns a raw
 * frame into a typed ClientMsg — or null, which the hub ignores. Malformed
 * input can never reach the sim or crash a room.
 */

import type { ClientMsg, Controls, ShopSlot } from "../shared";

/** Shop + powerup slots the protocol allows (keys 1–4, 7–0). */
const SHOP_SLOTS: readonly ShopSlot[] = [1, 2, 3, 4, 7, 8, 9, 0];

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null;

/** Coerce untrusted control flags: a missing field is a released key. */
function sanitizeControls(value: unknown): Controls {
  const c = (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
  return {
    thrust: c.thrust === true,
    back: c.back === true,
    left: c.left === true,
    right: c.right === true,
    shoot: c.shoot === true,
  };
}

/** Parse one raw WebSocket frame into a ClientMsg, or null when the frame
 * is not a message we accept (bad JSON, wrong types, unknown kind). */
export function parseClientMsg(raw: string): ClientMsg | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null; // binary noise or a truncated frame — not a protocol error
  }
  if (!isObject(value)) return null;
  switch (value.t) {
    case "join":
      if (typeof value.room !== "string" || typeof value.name !== "string") return null;
      return { t: "join", room: value.room, name: value.name };
    case "input": {
      if (typeof value.seq !== "number" || !Number.isFinite(value.seq)) return null;
      return { t: "input", seq: value.seq, controls: sanitizeControls(value.controls) };
    }
    case "buy":
      return SHOP_SLOTS.includes(value.slot as ShopSlot)
        ? { t: "buy", slot: value.slot as ShopSlot }
        : null;
    case "click":
      if (typeof value.x !== "number" || !Number.isFinite(value.x)) return null;
      if (typeof value.y !== "number" || !Number.isFinite(value.y)) return null;
      return { t: "click", x: value.x, y: value.y };
    case "restart":
      return { t: "restart" };
    default:
      return null;
  }
}
