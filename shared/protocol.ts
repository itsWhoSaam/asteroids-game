/**
 * The wire vocabulary — the only message shapes that cross the WebSocket,
 * imported by both the server and the client (spec: protocol.ts is the one
 * shared vocabulary). Types only, no runtime code, no platform imports.
 */

import type { BoughtPowerUpName, PowerUpKind, UpgradeName } from "./constants";

/** A shop slot: keys 1–4 buy upgrades, 7–0 fire bought powerups. */
export type ShopSlot = 1 | 2 | 3 | 4 | 7 | 8 | 9 | 0;

/**
 * Per-tick control intent — the replacement for pygame.key.get_pressed()
 * inside Player.update. The spec sketch's Controls plus `back`: the Python
 * ship polls S for reverse thrust, and dropping it would change gameplay.
 */
export interface Controls {
  thrust: boolean; // W
  back: boolean; // S
  left: boolean; // A
  right: boolean; // D
  shoot: boolean; // SPACE
}

/** Player-visible snapshot pieces (render targets, not sim state). */
export interface PlayerSnap {
  id: string;
  name: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  rotation: number; // degrees
  lives: number; // 0 = no ship (spectating until the run ends)
  score: number;
  invulnTimer: number; // > 0: the client blinks the ship
  shieldHits: number; // > 0: the client draws the shield ring
}

export interface AsteroidSnap {
  id: number;
  x: number;
  y: number;
  /** Effective velocity (chrono dilation already applied) for interpolation. */
  vx: number;
  vy: number;
  radius: number;
}

export interface ShotSnap {
  id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export interface PowerUpSnap {
  id: number;
  x: number;
  y: number;
  kind: PowerUpKind;
}

/** The shared ledger, as seen by every player in the room. */
export interface EconomySnap {
  credits: number;
  levels: Record<UpgradeName, number>;
  powerupUses: Partial<Record<BoughtPowerUpName, number>>;
  powerupTimers: Partial<Record<BoughtPowerUpName, number>>;
}

export type Phase = "playing" | "game_over";

/** Full world state for rendering; everything is plain JSON-safe data. */
export interface Snapshot {
  wave: number;
  phase: Phase;
  players: PlayerSnap[];
  asteroids: AsteroidSnap[];
  shots: ShotSnap[];
  powerups: PowerUpSnap[];
  economy: EconomySnap;
  /** Orbiting turret markers: angle in degrees plus the ship they ride. */
  drones: DroneSnap[];
}

export interface DroneSnap {
  orbitAngle: number;
  anchorId: string | null;
}

/**
 * Presentation events returned by the sim (and carried on snapshots).
 * The client maps them to WebAudio, particles, shake, and floating text —
 * replacing the sound/log calls the Python build fires inside its logic
 * paths. Extensions to the spec sketch, each client-necessary:
 * `explosion`/`playerHit` carry the wreck site for the debris burst,
 * `burst` is visual-only debris (the nuke path: Python bursts but never
 * plays a sound there), `mint` floats '+N' over a wreck, `pickup` rides
 * alongside the spec shape.
 */
export type GameEvent =
  | { k: "shoot" } // one blip per trigger pull, even on a TRIPLE volley
  | { k: "explosion"; size: 1 | 2 | 3; x: number; y: number } // burst + sound + (large) shake
  | { k: "burst"; x: number; y: number; radius: number } // visual-only debris
  | { k: "pickup"; kind: PowerUpKind }
  | { k: "playerHit"; playerId: string; x: number; y: number } // a life was lost
  | { k: "waveStarted"; wave: number }
  | { k: "gameOver" }
  | { k: "purchase"; what: UpgradeName | BoughtPowerUpName }
  | { k: "mint"; amount: number; x: number; y: number };

export type ClientMsg =
  | { t: "join"; room: string; name: string }
  | { t: "input"; seq: number; controls: Controls } // every tick while connected
  | { t: "buy"; slot: ShopSlot } // shop + powerup intents, server-gated
  | { t: "click"; x: number; y: number } // click-to-chip: server resolves the target
  | { t: "restart" };

export type ServerMsg =
  | { t: "welcome"; you: string; tickHz: 60; snapshot: Snapshot }
  | {
      t: "snapshot";
      tick: number;
      ack: number; // last input seq received from this client
      wave: number;
      phase: Phase;
      players: PlayerSnap[];
      asteroids: AsteroidSnap[];
      shots: ShotSnap[];
      powerups: PowerUpSnap[];
      economy: EconomySnap;
      drones: DroneSnap[];
      events: GameEvent[];
    }
  | { t: "rejected"; reason: "room-full" | "bad-code" };
