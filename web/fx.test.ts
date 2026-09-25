/**
 * Tests for the client-local cosmetics — the particles.py / FloatingText
 * ports. Pins the pure math: burst sizing, spawn pop, draw radius, shake
 * decay/cap/stop, and float lifetime.
 */
import { describe, expect, it } from "vitest";
import { FloatingTexts, ParticleField, Shake, burstCount, particleDrawRadius, spawnPop } from "./fx";

describe("burst sizing (particles.burst_count)", () => {
  it("scales with radius at 0.5 particles per radius", () => {
    expect(burstCount(20)).toBe(10); // small rock
    expect(burstCount(40)).toBe(20); // medium
    expect(burstCount(60)).toBe(30); // large
  });

  it("multiplies by intensity (the ship's death bursts harder)", () => {
    expect(burstCount(20, 4.0)).toBe(40);
  });

  it("never returns zero", () => {
    expect(burstCount(0)).toBe(1);
  });
});

describe("spark sizing", () => {
  it("pops at birth and eases to base size", () => {
    expect(spawnPop(1)).toBeCloseTo(1.6); // born oversized
    expect(spawnPop(0)).toBeCloseTo(1.0); // fully aged
  });

  it("draws smaller as life burns and floors at 1px", () => {
    expect(particleDrawRadius(1)).toBeGreaterThan(particleDrawRadius(0.5));
    expect(particleDrawRadius(0)).toBe(1);
  });
});

describe("Shake", () => {
  it("caps stacked kicks at the magnitude cap", () => {
    const shake = new Shake();
    shake.kick(14);
    shake.kick(14);
    expect(shake.currentMagnitude).toBe(20); // SHAKE_MAX_MAGNITUDE
  });

  it("decays exponentially and snaps to zero below the stop epsilon", () => {
    const shake = new Shake();
    shake.kick(14);
    shake.update(0.1); // 14 × 0.001^0.1 ≈ 7.02
    expect(shake.currentMagnitude).toBeCloseTo(14 * 0.001 ** 0.1, 1);
    shake.update(10); // anything meaningful drops far below the epsilon
    expect(shake.currentMagnitude).toBe(0);
  });

  it("offsets within the magnitude once kicked", () => {
    const shake = new Shake();
    expect(shake.offset()).toEqual({ x: 0, y: 0 });
    shake.kick(6);
    // Direction is random; only the per-axis bound is contractual.
    const offset = shake.offset();
    expect(Math.abs(offset.x)).toBeLessThanOrEqual(6);
    expect(Math.abs(offset.y)).toBeLessThanOrEqual(6);
    expect(offset.x !== 0 || offset.y !== 0).toBe(true);
  });
});

describe("ParticleField", () => {
  it("spawns burstCount particles and expires them at lifetime", () => {
    const field = new ParticleField();
    field.burst(0, 0, 20);
    expect(field.size).toBe(10);
    field.update(0.61); // past PARTICLE_LIFETIME_SECONDS
    expect(field.size).toBe(0);
  });

  it("clears on demand (restart hygiene)", () => {
    const field = new ParticleField();
    field.burst(0, 0, 60);
    expect(field.size).toBe(30);
    field.clear();
    expect(field.size).toBe(0);
  });
});

describe("FloatingTexts", () => {
  it("rises and dies at the lifetime", () => {
    const floats = new FloatingTexts();
    floats.spawn(100, 200, "+50", "yellow");
    floats.update(0.5);
    expect(floats.size).toBe(1);
    floats.update(0.6); // past FLOAT_LIFETIME_SECONDS total
    expect(floats.size).toBe(0);
  });

  it("clears on demand", () => {
    const floats = new FloatingTexts();
    floats.spawn(0, 0, "+1", "yellow");
    floats.clear();
    expect(floats.size).toBe(0);
  });
});
