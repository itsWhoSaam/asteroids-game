/**
 * Tests for the GameEvent → cosmetics mapper (main.py's inline wiring,
 * relocated). The sim stays pure; only the sink is touched.
 */
import { describe, expect, it, vi } from "vitest";
import type { GameEvent } from "../shared/protocol";
import { presentEvents, type CosmeticSink } from "./gamefx";
import { FloatingTexts, ParticleField, Shake } from "./fx";

function makeSink() {
  const audio = { play: vi.fn(), playExplosion: vi.fn(), setMuted: vi.fn() };
  const sink: CosmeticSink = {
    particles: new ParticleField(),
    shake: new Shake(),
    floats: new FloatingTexts(),
    audio,
  };
  return { sink, audio };
}

describe("presentEvents", () => {
  it("maps a shot to the shoot blip only", () => {
    const { sink, audio } = makeSink();
    presentEvents([{ k: "shoot" }], sink);
    expect(audio.play).toHaveBeenCalledWith("shoot");
    expect(audio.playExplosion).not.toHaveBeenCalled();
    expect(sink.particles.size).toBe(0);
  });

  it("maps an explosion to debris, a size-scaled shake, and the tiered sound", () => {
    const { sink, audio } = makeSink();
    presentEvents([{ k: "explosion", size: 2, x: 100, y: 200 }], sink);
    expect(sink.particles.size).toBeGreaterThan(0);
    expect(sink.shake.currentMagnitude).toBeGreaterThan(0);
    expect(audio.playExplosion).toHaveBeenCalledWith(2);
  });

  it("maps a visual burst to debris without sound", () => {
    const { sink, audio } = makeSink();
    presentEvents([{ k: "burst", x: 0, y: 0, radius: 30 }], sink);
    expect(sink.particles.size).toBeGreaterThan(0);
    expect(audio.play).not.toHaveBeenCalled();
    expect(audio.playExplosion).not.toHaveBeenCalled();
  });

  it("maps a player hit to the big burst, heavy shake, and the deepest tier", () => {
    const { sink, audio } = makeSink();
    presentEvents([{ k: "playerHit", playerId: "a", x: 5, y: 6 }], sink);
    expect(sink.shake.currentMagnitude).toBeGreaterThanOrEqual(8);
    expect(audio.playExplosion).toHaveBeenCalledWith(3);
  });

  it("maps game over to the game-over chord", () => {
    const { sink, audio } = makeSink();
    presentEvents([{ k: "gameOver" }], sink);
    expect(audio.play).toHaveBeenCalledWith("game_over");
  });

  it("mints float a +credits label at the event's position", () => {
    const { sink } = makeSink();
    presentEvents([{ k: "mint", amount: 20, x: 10, y: 20 }], sink);
    expect(sink.floats.size).toBe(1);
  });

  it("handles pickup, purchase, and wave events without floats", () => {
    const { sink, audio } = makeSink();
    presentEvents(
      [
        { k: "purchase", what: "nanoblade" },
        { k: "pickup", kind: "shield" },
        { k: "waveStarted", wave: 2 },
      ],
      sink,
    );
    expect(audio.play).toHaveBeenCalledWith("powerup"); // the pickup chirp
    expect(sink.floats.size).toBe(0);
  });

  it("handles an empty batch as a no-op", () => {
    const { sink, audio } = makeSink();
    presentEvents([] as GameEvent[], sink);
    expect(sink.particles.size).toBe(0);
    expect(sink.floats.size).toBe(0);
    expect(audio.play).not.toHaveBeenCalled();
  });
});
