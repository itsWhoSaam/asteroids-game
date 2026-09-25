// Public surface of the shared simulation — consumed by the Node server
// (authority) and the browser client (solo mode). No platform imports.
export * from "./constants";
export * from "./protocol";
export * from "./rng";
export {
  addPlayer,
  buy,
  chipThreshold,
  clickAt,
  clickDamage,
  dropsPowerup,
  incomeMultiplier,
  newWorld,
  pickPowerupType,
  pointsFor,
  powerupPrice,
  removePlayer,
  requestRestart,
  snapshot,
  step,
  upgradeCost,
  waveParams,
} from "./sim";
export type {
  AsteroidState,
  EconomyState,
  FieldState,
  PlayerState,
  PowerUpState,
  ShotState,
  Vec2,
  WaveParams,
  World,
} from "./sim";
