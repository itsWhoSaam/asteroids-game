/**
 * Client-local cosmetics: debris particles, screen shake, and floating
 * credit text — the presentation half of the desktop build's engagement
 * F5 plus main.py's FloatingText. Ported 1:1 from particles.py, with the
 * one structural difference the network forces: the sim cannot know about
 * these, so the client spawns them from GameEvents instead of the sweep
 * calling burst() directly.
 */
import {
  FLOAT_LIFETIME_SECONDS,
  FLOAT_RISE_SPEED,
  PALETTE,
  PARTICLE_LIFETIME_SECONDS,
  PARTICLE_MAX_SPEED,
  PARTICLE_MIN_SPEED,
  PARTICLE_RADIUS,
  PARTICLE_SPAWN_POP,
  PARTICLES_PER_RADIUS,
  SHAKE_DECAY,
  SHAKE_MAX_MAGNITUDE,
  SHAKE_STOP_EPSILON,
} from "../shared/constants";
import { fontCss } from "./fonts";

/** Pure burst sizing (particles.burst_count): the particle count scales
 * with the destroyed body's radius and intensity multiplier. */
export function burstCount(baseRadius: number, intensity = 1.0): number {
  return Math.max(1, Math.trunc(baseRadius * intensity * PARTICLES_PER_RADIUS));
}

/** Pure size-pop multiplier (visual V2): sparks are born slightly
 * oversized and ease down quadratically as life burns. */
export function spawnPop(lifeFraction: number): number {
  return 1.0 + PARTICLE_SPAWN_POP * lifeFraction ** 2;
}

/** Draw radius for one spark: base size scaled by remaining life and the
 * spawn pop, floored at 1px so the final moments still render. */
export function particleDrawRadius(lifeFraction: number): number {
  return Math.max(1, Math.round(PARTICLE_RADIUS * lifeFraction * spawnPop(lifeFraction)));
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  age: number;
}

/** A cloud of debris sparks: drift outward, age, die at their lifetime.
 * Cosmetics run on Math.random — determinism is a sim concern, not a
 * presentation one. */
export class ParticleField {
  private particles: Particle[] = [];

  /** Spawn one debris burst at (x, y) — particles.burst's port. */
  burst(x: number, y: number, baseRadius: number, intensity = 1.0): void {
    for (let i = 0; i < burstCount(baseRadius, intensity); i += 1) {
      const angle = Math.random() * Math.PI * 2;
      const speed =
        (PARTICLE_MIN_SPEED + Math.random() * (PARTICLE_MAX_SPEED - PARTICLE_MIN_SPEED)) * intensity;
      this.particles.push({ x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed, age: 0 });
    }
  }

  update(dt: number): void {
    for (const p of this.particles) {
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.age += dt;
    }
    this.particles = this.particles.filter((p) => p.age < PARTICLE_LIFETIME_SECONDS);
  }

  draw(ctx: CanvasRenderingContext2D): void {
    // Filled and shrinking: size-only fade keeps parity with the desktop
    // draw (no per-pixel alpha there either).
    ctx.fillStyle = rgbCss(PALETTE.spark);
    for (const p of this.particles) {
      const lifeFraction = Math.max(0, 1 - p.age / PARTICLE_LIFETIME_SECONDS);
      ctx.beginPath();
      ctx.arc(p.x, p.y, particleDrawRadius(lifeFraction), 0, Math.PI * 2);
      ctx.fill();
    }
  }

  clear(): void {
    this.particles.length = 0;
  }

  get size(): number {
    return this.particles.length;
  }
}

/** Screen shake as a decaying magnitude, applied at the draw origin only —
 * the exact particles.Shake port: entities never see this object. */
export class Shake {
  private magnitude = 0;

  /** Add trauma; a cap keeps stacked kicks from flinging the world. */
  kick(magnitude: number): void {
    this.magnitude = Math.min(this.magnitude + magnitude, SHAKE_MAX_MAGNITUDE);
  }

  /** Exponential decay with the clamped dt; below the stop threshold it
   * snaps to exactly zero. */
  update(dt: number): void {
    this.magnitude *= SHAKE_DECAY ** dt;
    if (this.magnitude < SHAKE_STOP_EPSILON) this.magnitude = 0;
  }

  /** The draw-origin shift for this frame: a fresh random direction at the
   * current magnitude. (0, 0) once still — the calm frame is pixel-identical
   * to a no-shake render. */
  offset(): { x: number; y: number } {
    if (this.magnitude <= 0) return { x: 0, y: 0 };
    const angle = Math.random() * Math.PI * 2;
    return { x: Math.cos(angle) * this.magnitude, y: Math.sin(angle) * this.magnitude };
  }

  get currentMagnitude(): number {
    return this.magnitude;
  }
}

export interface FloatingLabel {
  x: number;
  y: number;
  label: string;
  color: string;
  life: number;
}

/** Rising '+N' credit numbers and purchase/powerup labels — main.py's
 * FloatingText group. Lifetime runs on the dt-timer pattern. */
export class FloatingTexts {
  private items: FloatingLabel[] = [];

  spawn(x: number, y: number, label: string, color: string): void {
    this.items.push({ x, y, label, color, life: FLOAT_LIFETIME_SECONDS });
  }

  update(dt: number): void {
    for (const item of this.items) {
      item.life -= dt;
      item.y -= FLOAT_RISE_SPEED * dt;
    }
    this.items = this.items.filter((item) => item.life > 0);
  }

  draw(ctx: CanvasRenderingContext2D): void {
    ctx.font = fontCss(20, 700);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const item of this.items) {
      ctx.fillStyle = item.color;
      ctx.fillText(item.label, item.x, item.y);
    }
  }

  clear(): void {
    this.items.length = 0;
  }

  get size(): number {
    return this.items.length;
  }
}

/** Palette RGB → canvas color string. */
export function rgbCss([r, g, b]: readonly [number, number, number], alpha = 1): string {
  return alpha >= 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
