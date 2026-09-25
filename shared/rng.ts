/**
 * Seeded PRNG for the shared simulation. The world's randomness is injected
 * (`World.rng`) — the server seeds per room, solo mode per session, and
 * replay tests with a fixed seed are exactly reproducible. No platform
 * imports: this module runs in the browser and Node alike.
 */

export type Rng = () => number;

/**
 * mulberry32: tiny, fast, well-distributed 32-bit PRNG returning [0, 1).
 * The Python build uses global `random`, which two machines can never
 * agree on bit-for-bit — the shared sim instead takes its generator as
 * state, so a room's whole trajectory is a function of the seed.
 */
export function mulberry32(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
