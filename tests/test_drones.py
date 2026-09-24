"""Tests for idle drones: turret cadence and aiming, fleet sync, and the
capped offline grant through the Economy ledger."""

import time

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    DRONE_CREDITS_PER_SHOT,
    DRONE_FIRE_INTERVAL_S,
    DRONE_SHOT_SPEED,
    OFFLINE_BANNER_SECONDS,
    OFFLINE_CAP_SECONDS,
    OFFLINE_RATE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from drones import DroneBay, DroneTurret, OfflineBanner, drone_dps
from economy import Economy
from game import Game
from hud import points_for
from main import destroyed_asteroids, handle_collisions
from player import Player
from shot import Shot


@pytest.fixture
def economy(tmp_path):
    """An Economy on a private save path (missing file → fresh defaults)."""
    return Economy(save_path=str(tmp_path / "game_save.json"))


@pytest.fixture
def player():
    return Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)

    return updatable, drawable, asteroids, shots


# --- turret firing ---------------------------------------------------------


def test_drone_timer_spawns_a_shot_into_the_group(player):
    """Crossing the fire interval puts one real Shot in the shared group."""
    _updatable, _drawable, asteroids, shots = make_groups()
    turret = DroneTurret(0, 1)

    turret.update(0.7, player, asteroids, shots)  # stagger is 0.75 s
    assert len(shots) == 0

    turret.update(0.1, player, asteroids, shots)
    assert len(shots) == 1
    shot = list(shots)[0]
    assert isinstance(shot, Shot)
    assert shot.velocity.length() == pytest.approx(DRONE_SHOT_SPEED)


def test_drone_interval_is_honored_between_shots(player):
    """After the first fire, the next shot waits a full interval — overshoot
    carries, so the cadence stays a true 1.5 s, not 'up to 1.5 s'."""
    _updatable, _drawable, asteroids, shots = make_groups()
    turret = DroneTurret(0, 1)

    turret.update(0.7, player, asteroids, shots)
    turret.update(0.1, player, asteroids, shots)  # fires (cumulative 0.8 s)
    assert len(shots) == 1

    turret.update(1.4, player, asteroids, shots)  # cumulative 2.2 s
    assert len(shots) == 1

    turret.update(0.1, player, asteroids, shots)  # cumulative 2.3 s → fires
    assert len(shots) == 2


def test_zero_drone_level_spawns_nothing(economy, player):
    """Zero turrets, zero shots, zero cost — the level owns everything."""
    _updatable, _drawable, asteroids, shots = make_groups()
    bay = DroneBay(economy)
    assert economy.levels["drone"] == 0

    bay.update(DRONE_FIRE_INTERVAL_S * 3, player, asteroids, shots)

    assert bay.turrets == []
    assert len(shots) == 0


def test_fleet_size_follows_the_drones_level(economy):
    """sync() grows and shrinks the turret list to match the ledger."""
    bay = DroneBay(economy)
    economy.levels["drone"] = 3
    bay.sync()
    assert len(bay.turrets) == 3

    economy.levels["drone"] = 1
    bay.sync()
    assert len(bay.turrets) == 1


# --- aiming ----------------------------------------------------------------


def test_drone_aims_at_the_nearest_asteroid(player):
    _updatable, _drawable, asteroids, _shots = make_groups()
    turret = DroneTurret(0, 1)
    muzzle = turret.muzzle(player)
    Asteroid(muzzle.x, muzzle.y - 200, ASTEROID_MIN_RADIUS)  # directly above
    Asteroid(muzzle.x + 1000, muzzle.y, ASTEROID_MIN_RADIUS * 3)  # far away

    aim = turret.aim(player, asteroids)
    assert aim.x == pytest.approx(0.0, abs=1e-6)
    assert aim.y == pytest.approx(-1.0, abs=1e-6)


def test_drone_without_targets_fires_straight_ahead(player):
    """No asteroid in the field: the shot goes out along the ship's nose."""
    player.rotation = 90
    turret = DroneTurret(0, 1)
    assert turret.aim(player, []) == pygame.Vector2(-1, 0)


# --- the shared destruction path -------------------------------------------


def test_drone_kill_mints_through_the_shared_pipeline(economy, player, tmp_path):
    """A drone kill is indistinguishable from a player-shot kill: the same
    sweep splits the rock, and the same destruction diff mints the payout."""
    updatable, _drawable, asteroids, shots = make_groups()
    game = Game(player, asteroids, shots, save_path=str(tmp_path / "game_save.json"))
    economy.levels["drone"] = 1
    bay = DroneBay(economy)
    bay.sync()  # level 1 → exactly one turret
    turret = bay.turrets[0]
    muzzle = turret.muzzle(player)
    asteroid = Asteroid(muzzle.x, muzzle.y + 120, ASTEROID_MIN_RADIUS)  # below

    prev = set(asteroids)
    for _ in range(150):  # ~2.5 s: fire (0.75 s) plus the shot's travel time
        bay.update(1 / 60, player, asteroids, shots)
        updatable.update(1 / 60)  # move the shots, exactly like main()'s loop
        handle_collisions(asteroids, shots, player, game, pygame.sprite.Group())
        wrecks = destroyed_asteroids(prev, asteroids)
        prev = set(asteroids)
        if wrecks:
            economy.mint(wrecks[0].radius)
            break

    assert not asteroid.alive()
    assert economy.credits == pytest.approx(points_for(ASTEROID_MIN_RADIUS))


# --- offline earnings ------------------------------------------------------


def test_apply_offline_caps_at_the_cap_and_halves(economy):
    """Ten hours away pays exactly the 8-hour cap at half rate."""
    earned = economy.apply_offline(OFFLINE_CAP_SECONDS * 10, 10.0)
    assert earned == pytest.approx(10.0 * OFFLINE_CAP_SECONDS * OFFLINE_RATE)
    assert economy.credits == pytest.approx(earned)


def test_apply_offline_pays_elapsed_under_the_cap(economy):
    earned = economy.apply_offline(3600.0, 10.0)
    assert earned == pytest.approx(10.0 * 3600.0 * OFFLINE_RATE)


def test_missing_last_seen_grants_nothing_and_raises_nothing(economy):
    """A save without idle_last_seen (fresh install, pre-drones save) must
    neither crash nor pay the capped maximum — it grants zero."""
    assert economy.last_seen == 0.0
    assert economy.claim_offline(100.0) == 0.0
    assert economy.credits == 0.0


def test_claim_offline_uses_the_saved_stamp_and_re_stamps(economy):
    economy.last_seen = 1000.0
    granted = economy.claim_offline(10.0, now=1000.0 + 3600.0)
    assert granted == pytest.approx(10.0 * 3600.0 * OFFLINE_RATE)
    assert economy.last_seen == 1000.0 + 3600.0  # re-stamped: no double-pay


def test_offline_grant_survives_the_save_roundtrip(tmp_path):
    """Grant, save, boot fresh: the credits and the Drones level reload."""
    path = str(tmp_path / "game_save.json")
    before = Economy(save_path=path)
    before.levels["drone"] = 2
    before.last_seen = time.time() - 3600  # one hour away

    granted = before.claim_offline(drone_dps(before.levels["drone"]))
    assert granted == pytest.approx(drone_dps(2) * 3600 * OFFLINE_RATE)
    before.save()

    fresh = Economy(save_path=path)
    assert fresh.credits == pytest.approx(granted)
    assert fresh.levels["drone"] == 2
    assert fresh.last_seen > 0


def test_drone_dps_scales_with_level_and_zero_pays_nothing():
    assert drone_dps(0) == 0.0
    assert drone_dps(2) == pytest.approx(
        2 * DRONE_CREDITS_PER_SHOT / DRONE_FIRE_INTERVAL_S
    )


def test_offline_banner_fades_and_zero_grant_never_shows():
    banner = OfflineBanner(1234.0)
    assert banner.lifetime == OFFLINE_BANNER_SECONDS
    banner.update(OFFLINE_BANNER_SECONDS + 1)
    assert banner.lifetime <= 0

    assert OfflineBanner(0.0).lifetime == 0.0
