/**
 * Table-pinning tests: every value here is the PYTHON LITERAL, hardcoded
 * from constants.py (never imported from the TS module — that would make
 * the test circular). A failure names the drifted table and both values.
 * Port rule: with constants.py open, never from memory.
 */
import { describe, expect, it } from "vitest";
import * as C from "./constants";

describe("constants.py tables — pinned verbatim", () => {
  it("pins the screen and player scalars", () => {
    expect(C.SCREEN_WIDTH).toBe(1280); // constants.py: SCREEN_WIDTH
    expect(C.SCREEN_HEIGHT).toBe(720); // constants.py: SCREEN_HEIGHT
    expect(C.PLAYER_RADIUS).toBe(20);
    expect(C.LINE_WIDTH).toBe(2);
    expect(C.PLAYER_TURN_SPEED).toBe(300);
    expect(C.PLAYER_SPEED).toBe(200);
  });

  it("pins the asteroid field scalars", () => {
    expect(C.ASTEROID_MIN_RADIUS).toBe(20);
    expect(C.ASTEROID_KINDS).toBe(3);
    expect(C.ASTEROID_SPAWN_RATE_SECONDS).toBe(0.8);
    expect(C.ASTEROID_MAX_RADIUS).toBe(20 * 3); // MIN * KINDS
  });

  it("pins the shot scalars", () => {
    expect(C.SHOT_RADIUS).toBe(5);
    expect(C.PLAYER_SHOOT_SPEED).toBe(500);
    expect(C.PLAYER_SHOOT_COOLDOWN_SECONDS).toBe(0.3);
    expect(C.MAX_DT).toBe(0.1);
  });

  it("pins the scoring table (smaller rocks pay more)", () => {
    expect(C.SCORE_LARGE).toBe(20);
    expect(C.SCORE_MEDIUM).toBe(50);
    expect(C.SCORE_SMALL).toBe(100);
  });

  it("pins the lives table", () => {
    expect(C.PLAYER_START_LIVES).toBe(3);
    expect(C.PLAYER_INVULNERABILITY_SECONDS).toBe(2.0);
    expect(C.PLAYER_BLINK_HZ).toBe(4);
  });

  it("pins the game-over overlay scalars", () => {
    expect(C.GAME_OVER_FONT_SIZE).toBe(48);
    expect(C.GAME_OVER_LINE_STEP).toBe(60);
  });

  it("pins the wave progression table", () => {
    expect(C.WAVE_SPAWN_DECAY).toBe(0.9);
    expect(C.WAVE_SPAWN_INTERVAL_FLOOR).toBe(0.3);
    expect(C.ASTEROID_SPEED_MIN).toBe(40);
    expect(C.ASTEROID_SPEED_MAX).toBe(100);
    expect(C.WAVE_SPEED_MIN_STEP).toBe(10);
    expect(C.WAVE_SPEED_MAX_STEP).toBe(15);
    expect(C.WAVE_BANNER_SECONDS).toBe(2.0);
  });

  it("pins the HUD scalars", () => {
    expect(C.HUD_FONT_SIZE).toBe(28);
    expect(C.HUD_MARGIN).toBe(12);
    expect(C.HUD_LINE_STEP).toBe(34);
  });

  it("pins the PALETTE swatches to the Python RGB tuples", () => {
    // constants.py: PALETTE = { "paper": (23, 18, 58), ... }
    expect(C.PALETTE.paper).toEqual([23, 18, 58]);
    expect(C.PALETTE.ship).toEqual([62, 230, 240]);
    expect(C.PALETTE.fringe_r).toEqual([255, 51, 85]);
    expect(C.PALETTE.fringe_c).toEqual([47, 212, 255]);
    expect(C.PALETTE.asteroid_l).toEqual([180, 77, 255]);
    expect(C.PALETTE.asteroid_m).toEqual([255, 45, 149]);
    expect(C.PALETTE.asteroid_s).toEqual([255, 107, 213]);
    expect(C.PALETTE.shot).toEqual([255, 233, 74]);
    expect(C.PALETTE.powerup_shield).toEqual([62, 230, 240]);
    expect(C.PALETTE.powerup_rapid).toEqual([255, 154, 62]);
    expect(C.PALETTE.powerup_triple).toEqual([255, 78, 205]);
    expect(C.PALETTE.spark).toEqual([255, 210, 63]);
    expect(C.PALETTE.hud_ink).toEqual([255, 247, 230]);
    expect(C.PALETTE.hud_panel).toEqual([255, 210, 63]);
    expect(C.PALETTE.banner).toEqual([255, 210, 63]);
    // HUD_COLOR = PALETTE["hud_ink"] — the same array object in Python.
    expect(C.HUD_COLOR).toEqual([255, 247, 230]);
  });

  it("pins the idle-economy core scalars", () => {
    expect(C.CLICK_DAMAGE_BASE).toBe(1.0);
    expect(C.CHIP_HEALTH_PER_TIER).toBe(3.0);
    expect(C.FLOAT_FONT_SIZE).toBe(20);
    expect(C.FLOAT_LIFETIME_SECONDS).toBe(1.0);
    expect(C.FLOAT_RISE_SPEED).toBe(40.0);
    expect(C.FLOAT_COLOR).toBe("yellow");
    expect(C.IDLE_AUTOSAVE_SECONDS).toBe(30.0);
  });

  it("pins the UPGRADE_COSTS curves", () => {
    // constants.py: UPGRADE_COSTS = { "nanoblade": (10.0, 1.75), ... }
    expect(C.UPGRADE_COSTS.nanoblade).toEqual([10.0, 1.75]);
    expect(C.UPGRADE_COSTS.fire_rate).toEqual([25.0, 1.9]);
    expect(C.UPGRADE_COSTS.income).toEqual([50.0, 2.0]);
    expect(C.UPGRADE_COSTS.drone).toEqual([100.0, 2.2]);
  });

  it("pins the shop multipliers and panel scalars", () => {
    expect(C.NANOBLADE_MULT_PER_LEVEL).toBe(1.8);
    expect(C.FIRE_RATE_MULT_PER_LEVEL).toBe(0.88);
    expect(C.PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS).toBe(0.03);
    expect(C.INCOME_MULT_PER_LEVEL).toBe(1.15);
    expect(C.SHOP_FONT_SIZE).toBe(18);
    expect(C.SHOP_PANEL_HEIGHT).toBe(64);
    expect(C.SHOP_CELL_PADDING).toBe(10);
    expect(C.SHOP_LINE_STEP).toBe(22);
    expect(C.SHOP_PANEL_BG).toEqual([16, 16, 28]);
    expect(C.SHOP_PANEL_BORDER).toEqual([70, 70, 90]);
    expect(C.SHOP_DIM_COLOR).toEqual([100, 100, 100]);
    expect(C.SHOP_BRIGHT_COLOR).toEqual([255, 230, 120]);
  });

  it("pins the upgrade defs (titles, key chars, effect copy)", () => {
    // Python binds pygame.K_1..K_4; the key LABEL is the digit chr(K_n).
    expect(C.UPGRADE_DEFS).toHaveLength(4);
    const byName = Object.fromEntries(C.UPGRADE_DEFS.map((d) => [d.name, d]));
    expect(byName.nanoblade).toMatchObject({ title: "Nanoblade", key: "1", effect: "click damage ×1.8/lvl" });
    expect(byName.fire_rate).toMatchObject({ title: "Fire-rate", key: "2", effect: "shot cooldown ×0.88/lvl" });
    expect(byName.income).toMatchObject({ title: "Income", key: "3", effect: "credit payouts ×1.15/lvl" });
    expect(byName.drone).toMatchObject({ title: "Drones", key: "4", effect: "auto-turret per level" });
  });

  it("pins the drone table", () => {
    expect(C.DRONE_FIRE_INTERVAL_S).toBe(1.5);
    expect(C.DRONE_SHOT_SPEED).toBe(500);
    expect(C.DRONE_ORBIT_RADIUS).toBe(36);
    expect(C.DRONE_ORBIT_SPEED).toBe(72.0);
    expect(C.DRONE_MARKER_RADIUS).toBe(5);
    expect(C.DRONE_MARKER_COLOR).toEqual([90, 220, 200]);
    expect(C.DRONE_CREDITS_PER_SHOT).toBe(50.0);
  });

  it("pins the offline-earnings table", () => {
    expect(C.OFFLINE_CAP_SECONDS).toBe(8 * 3600);
    expect(C.OFFLINE_RATE).toBe(0.5);
    expect(C.OFFLINE_BANNER_SECONDS).toBe(4.0);
  });

  it("pins the POWERUPS table (bought activations)", () => {
    // constants.py: {"title": ..., "cost": ..., "key": pygame.K_7, "duration": ..., "desc": ...}
    expect(C.POWERUPS.gold_rush).toMatchObject({ title: "Gold Rush", cost: 400, key: "7", duration: 15.0, desc: "credit income ×5" });
    expect(C.POWERUPS.nuke).toMatchObject({ title: "Nuke", cost: 1000, key: "8", duration: 0.0, desc: "clear the field, full payout" });
    expect(C.POWERUPS.overdrive).toMatchObject({ title: "Overdrive", cost: 250, key: "9", duration: 10.0, desc: "click damage ×10" });
    expect(C.POWERUPS.chrono).toMatchObject({ title: "Chrono", cost: 300, key: "0", duration: 8.0, desc: "asteroid speed ×0.5" });
    // Escalating per-use price growth.
    expect(C.POWERUP_PER_USE_PRICE_GROWTH).toBe(1.25);
  });

  it("pins the powerup magnitudes", () => {
    expect(C.POWERUP_GOLD_RUSH_MULT).toBe(5.0);
    expect(C.POWERUP_OVERDRIVE_MULT).toBe(10.0);
    expect(C.POWERUP_CHRONO_SLOW).toBe(0.5);
  });

  it("pins the active color to the SECOND Python assignment", () => {
    // constants.py assigns POWERUP_ACTIVE_COLOR twice: (120, 255, 180) in the
    // F-powerup block, then (255, 160, 40) in the insane-powerups block — the
    // second wins at import time. The mirror pins the effective value.
    expect(C.POWERUP_ACTIVE_COLOR).toEqual([255, 160, 40]);
    expect(C.POWERUP_COLOR).toEqual([170, 120, 255]);
  });

  it("pins the drop-pickup table", () => {
    expect(C.POWERUP_DROP_CHANCE).toBe(0.15);
    expect(C.POWERUP_DURATION_S.shield).toBe(8.0);
    expect(C.POWERUP_DURATION_S.rapid).toBe(8.0);
    expect(C.POWERUP_DURATION_S.triple).toBe(8.0);
    expect(C.POWERUP_RAPID_COOLDOWN_MULT).toBe(0.4);
    expect(C.POWERUP_TRIPLE_SPREAD).toBe(20.0);
    expect(C.POWERUP_SHIELD_HITS).toBe(1);
    expect(C.POWERUP_RADIUS).toBe(14);
    expect(C.POWERUP_DRIFT_SPEED).toBe(30);
    expect(C.POWERUP_FONT_SIZE).toBe(20);
    expect(C.POWERUP_SHIELD_RING_GAP).toBe(8);
  });

  it("pins the particle and shake table", () => {
    expect(C.PARTICLES_PER_RADIUS).toBe(0.5);
    expect(C.PARTICLE_LIFETIME_SECONDS).toBe(0.6);
    expect(C.PARTICLE_RADIUS).toBe(3);
    expect(C.PARTICLE_SPAWN_POP).toBe(0.6);
    expect(C.PARTICLE_MIN_SPEED).toBe(40);
    expect(C.PARTICLE_MAX_SPEED).toBe(160);
    expect(C.PLAYER_DEATH_BURST_INTENSITY).toBe(4.0);
    expect(C.SHAKE_DECAY).toBe(0.001);
    expect(C.SHAKE_STOP_EPSILON).toBe(0.1);
    expect(C.SHAKE_MAX_MAGNITUDE).toBe(20);
    expect(C.SHAKE_PLAYER_DEATH).toBe(14.0);
    expect(C.SHAKE_LARGE_ASTEROID).toBe(6.0);
  });

  it("pins the sound table", () => {
    expect(C.SFX_SAMPLE_RATE).toBe(44100);
    expect(C.SFX_FORMAT).toBe(-16);
    expect(C.SFX_CHANNELS).toBe(2);
    expect(C.SFX_NOISE_SEED).toBe(7);
    expect(C.SFX_SHOOT).toBe("shoot");
    expect(C.SFX_EXPLOSION_SMALL).toBe("explosion_small");
    expect(C.SFX_EXPLOSION_MEDIUM).toBe("explosion_medium");
    expect(C.SFX_EXPLOSION_LARGE).toBe("explosion_large");
    expect(C.SFX_POWERUP).toBe("powerup");
    expect(C.SFX_GAME_OVER).toBe("game_over");
    expect(C.SFX_SHOOT_DURATION).toBe(0.10);
    expect(C.SFX_SHOOT_SWEEP).toEqual([900.0, 300.0]);
    expect(C.SFX_SHOOT_VOLUME).toBe(0.5);
    expect(C.SFX_EXPLOSION_VOLUME).toBe(0.6);
    expect(C.SFX_EXPLOSION_TIERS.small).toEqual({ duration: 0.18, thump_hz: 220.0, brightness: 0.8 });
    expect(C.SFX_EXPLOSION_TIERS.medium).toEqual({ duration: 0.30, thump_hz: 120.0, brightness: 0.6 });
    expect(C.SFX_EXPLOSION_TIERS.large).toEqual({ duration: 0.45, thump_hz: 70.0, brightness: 0.5 });
    expect(C.SFX_POWERUP_DURATION).toBe(0.22);
    expect(C.SFX_POWERUP_SWEEP).toEqual([300.0, 900.0]);
    expect(C.SFX_POWERUP_VOLUME).toBe(0.5);
    expect(C.SFX_GAME_OVER_DURATION).toBe(0.8);
    expect(C.SFX_GAME_OVER_SWEEP).toEqual([440.0, 90.0]);
    expect(C.SFX_GAME_OVER_VOLUME).toBe(0.6);
  });
});
