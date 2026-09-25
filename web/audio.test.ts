/**
 * Tests for the WebAudio synthesis port — the pure sample math from
 * sound.py:131–215. Pins the chirp integral, each effect's envelope shape,
 * sample counts, clamping, determinism of the seeded explosion noise, and
 * the GameEvent tier mapping. The AudioContext glue is dogfood-verified.
 */
import { describe, expect, it } from "vitest";
import {
  SFX_EXPLOSION_TIERS,
  SFX_SAMPLE_RATE,
  SFX_SHOOT_DURATION,
} from "../shared/constants";
import {
  chirp,
  explosionSamples,
  explosionWave,
  gameOverSamples,
  gameOverWave,
  powerupSamples,
  powerupWave,
  renderSamples,
  shootSamples,
  shootWave,
  synthTable,
  tierForSize,
} from "./audio";
describe("chirp (exact phase integral)", () => {
  it("is zero at t=0 regardless of the sweep", () => {
    expect(chirp(0, 900, 300, 0.1)).toBe(0);
    expect(chirp(0, 300, 900, 0.22)).toBe(0);
  });

  it("lands on a known value mid-sweep", () => {
    // mid=600, half=−300: sin(2π(600·0.05 − 300·0.0025/0.1)) = sin(45π) = 0
    expect(chirp(0.05, 900, 300, 0.1)).toBeCloseTo(0, 10);
    // rising sweep through a quarter period: sin(2π(600·0.05 + 300·0.0025/0.1))
    //   = sin(2π·37.5) = 0 as well; use a non-symmetric instant instead:
    expect(chirp(0.1, 900, 300, 0.1)).toBeCloseTo(Math.sin(2 * Math.PI * 30), 10);
  });

  it("stays within [−1, 1]", () => {
    for (let i = 0; i <= 100; i += 1) {
      const value = chirp((i / 100) * 0.1, 900, 300, 0.1);
      expect(Math.abs(value)).toBeLessThanOrEqual(1);
    }
  });
});

describe("envelope shapes", () => {
  it("the shoot decays exponentially from its volume", () => {
    const [start, end] = [900, 300];
    expect(shootWave(0, 0)).toBeCloseTo(chirp(0, start, end, SFX_SHOOT_DURATION) * 0.5, 12);
    // t=0.02 keeps the carrier away from a zero crossing: chirp = −0.951.
    expect(Math.abs(shootWave(0.02, 0.5))).toBeLessThan(Math.abs(shootWave(0.02, 0)));
    expect(shootWave(0, 1)).toBeCloseTo(shootWave(0, 0) * Math.exp(-6.0), 12);
  });

  it("the powerup window closes at both ends and opens mid-sweep", () => {
    expect(powerupWave(0, 0)).toBe(0); // attack edge
    expect(powerupWave(0, 1)).toBe(0); // release edge
    expect(powerupWave(0, 0.5)).toBeCloseTo(chirp(0, 300, 900, 0.22) * 0.5, 12);
    expect(Math.abs(powerupWave(0, 0.25))).toBe(0); // t=0: the chirp carrier itself is zero
    // t=0.05 keeps the carrier (chirp ≈ 0.54) away from its zero crossing.
    expect(Math.abs(powerupWave(0.05, 0.25))).toBeGreaterThan(0);
  });

  it("the game-over tone fades linearly", () => {
    expect(gameOverWave(0, 0)).toBeCloseTo(chirp(0, 440, 90, 0.8) * 0.6, 12);
    expect(gameOverWave(0, 1)).toBeCloseTo(0, 12);
    expect(Math.abs(gameOverWave(0, 0.25))).toBeCloseTo(Math.abs(gameOverWave(0, 0)) * 0.75, 12);
  });

  it("the explosion mixes noise and a halving thump under one decay", () => {
    const params = SFX_EXPLOSION_TIERS.small;
    const t = 0.01;
    const expected =
      (0.4 * params.brightness + chirp(t, params.thump_hz, params.thump_hz * 0.5, params.duration) * (1 - 0.25)) *
      Math.exp(-4.0 * 0.25) *
      0.6;
    expect(explosionWave(t, 0.25, "small", 0.4)).toBeCloseTo(expected, 12);
    // A louder noise draw moves the mix further from zero.
    expect(Math.abs(explosionWave(t, 0.25, "large", 1))).toBeGreaterThan(
      Math.abs(explosionWave(t, 0.25, "large", 0.1)),
    );
  });
});

describe("renderSamples", () => {
  it("produces the exact frame count the desktop truncates to", () => {
    expect(shootSamples()).toHaveLength(Math.trunc(SFX_SAMPLE_RATE * SFX_SHOOT_DURATION)); // 4410
    expect(powerupSamples()).toHaveLength(Math.trunc(SFX_SAMPLE_RATE * 0.22)); // 9702
    expect(explosionSamples("small")).toHaveLength(Math.trunc(SFX_SAMPLE_RATE * 0.18)); // 7938
    expect(explosionSamples("large")).toHaveLength(Math.trunc(SFX_SAMPLE_RATE * 0.45)); // 19845
    expect(gameOverSamples()).toHaveLength(Math.trunc(SFX_SAMPLE_RATE * 0.8)); // 35280
  });

  it("clamps into [−1, 1]", () => {
    const samples = renderSamples(0.001, () => 5);
    expect(samples.every((value) => value <= 1 && value >= -1)).toBe(true);
  });

  it("walks t in seconds and progress in [0, 1)", () => {
    const calls: Array<[number, number]> = [];
    renderSamples(2 / SFX_SAMPLE_RATE, (t, progress) => {
      calls.push([t, progress]);
      return 0;
    });
    expect(calls[0]).toEqual([0, 0]);
    expect(calls[1]).toEqual([1 / SFX_SAMPLE_RATE, 0.5]);
  });
});

describe("determinism", () => {
  it("the explosion buffers are identical across builds from the same seed", () => {
    const first = explosionSamples("medium");
    const second = explosionSamples("medium");
    expect(first).toEqual(second);
  });

  it("the synth table covers all six desktop sounds", () => {
    const table = synthTable();
    expect(table.map(([name]) => name)).toEqual([
      "shoot",
      "explosion_small",
      "explosion_medium",
      "explosion_large",
      "powerup",
      "game_over",
    ]);
    expect(table.every(([, samples]) => samples.length > 0)).toBe(true);
  });
});

describe("tier mapping", () => {
  it("maps event sizes to explosion tiers", () => {
    expect(tierForSize(1)).toBe("small");
    expect(tierForSize(2)).toBe("medium");
    expect(tierForSize(3)).toBe("large");
  });
});
