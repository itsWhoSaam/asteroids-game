/**
 * Snapshot interpolation — the client's render source in rooms. The server
 * broadcasts ~20 Hz; the display runs at display rate, so the renderer
 * walks between the last two received snapshots instead of jumping.
 *
 * Pure and DOM-free: LerpBuffer holds the timing, interpolateSnaps does the
 * entity-matched math, and neither touches the simulation. Clients send
 * intent and render history — they never advance the shared sim.
 */
import type { PlayerSnap, Snapshot } from "../shared/protocol";

/** Server cadence is ~20 Hz (every 3rd 60 Hz tick); the render clock lags
 * one interval behind the newest snapshot for smooth interpolation. */
export const DEFAULT_SNAPSHOT_INTERVAL_MS = 50;

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Shortest-arc degree interpolation — a ship crossing the 0°/360° seam
 * must sweep 20°, not spin 340° backwards. */
export function lerpAngleDeg(a: number, b: number, t: number): number {
  let delta = (b - a) % 360;
  if (delta > 180) delta -= 360;
  if (delta < -180) delta += 360;
  // 350° + half of a +20° arc is 0°, not 360° — normalize the result.
  return (a + delta * t + 360) % 360;
}

function byId<T extends { id: number }>(items: T[]): Map<number, T> {
  return new Map(items.map((item) => [item.id, item]));
}

function lerpPlayer(prev: PlayerSnap, next: PlayerSnap, alpha: number): PlayerSnap {
  return {
    ...next,
    x: lerp(prev.x, next.x, alpha),
    y: lerp(prev.y, next.y, alpha),
    rotation: lerpAngleDeg(prev.rotation, next.rotation, alpha),
  };
}

function lerpEntity<T extends { id: number; x: number; y: number }>(prev: T, next: T, alpha: number): T {
  return { ...next, x: lerp(prev.x, next.x, alpha), y: lerp(prev.y, next.y, alpha) };
}

/** Entity-matched interpolation between two snapshots: ids present in both
 * lerp; ids only in `next` are new spawns (use next); ids only in `prev`
 * are already gone (dropped — death and culls catch up on the next snap).
 * Scalars (wave, phase, economy, events) come from `next`: the newest
 * authoritative values. */
export function interpolateSnaps(prev: Snapshot, next: Snapshot, alpha: number): Snapshot {
  const t = Math.min(1, Math.max(0, alpha));
  const prevPlayers = new Map(prev.players.map((p) => [p.id, p]));
  const prevAsteroids = byId(prev.asteroids);
  const prevShots = byId(prev.shots);
  const prevPowerups = byId(prev.powerups);

  const players = next.players.map((p) => {
    const before = prevPlayers.get(p.id);
    return before ? lerpPlayer(before, p, t) : p;
  });
  const asteroids = next.asteroids.map((a) => {
    const before = prevAsteroids.get(a.id);
    return before ? lerpEntity(before, a, t) : a;
  });
  const shots = next.shots.map((s) => {
    const before = prevShots.get(s.id);
    return before ? lerpEntity(before, s, t) : s;
  });
  const powerups = next.powerups.map((pu) => {
    const before = prevPowerups.get(pu.id);
    return before ? lerpEntity(before, pu, t) : pu;
  });

  return { ...next, players, asteroids, shots, powerups };
}

interface TimedSnap {
  snap: Snapshot;
  atMs: number;
}

/** The short lerp buffer: exactly the last two snapshots. */
export class LerpBuffer {
  private prev: TimedSnap | null = null;
  private next: TimedSnap | null = null;

  /** Record one arrived snapshot. Stale (older than the newest) pushes are
   * ignored — a reordered delivery must not rewind the buffer. */
  push(snap: Snapshot, atMs: number): void {
    if (this.next && atMs <= this.next.atMs) return;
    this.prev = this.next;
    this.next = { snap, atMs };
  }

  reset(): void {
    this.prev = null;
    this.next = null;
  }

  /** The world to render at `nowMs`: the two newest snapshots walked by
   * how far the (delayed) render clock has moved between their arrival
   * times. Returns null before the first snapshot. Holds at the newest
   * snapshot when it ages past the window — interpolation only, never
   * extrapolation: the client never advances the shared sim. */
  sample(nowMs: number, intervalMs = DEFAULT_SNAPSHOT_INTERVAL_MS): Snapshot | null {
    if (!this.next) return null;
    if (!this.prev) return this.next.snap;
    const gap = this.next.atMs - this.prev.atMs;
    if (gap <= 0) return this.next.snap;
    const renderAt = nowMs - intervalMs;
    const alpha = (renderAt - this.prev.atMs) / gap;
    if (alpha >= 1) return this.next.snap;
    return interpolateSnaps(this.prev.snap, this.next.snap, alpha);
  }
}
