"""Tests for the bought powerups (insane-powerups): gated activation,
escalating per-use prices, expiry restoring base values, the nuke's
single-payout invariant, chrono dilation, and the idle_* save roundtrip.
"""

import json

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    POWERUP_PER_USE_PRICE_GROWTH,
    POWERUPS,
)
from economy import Economy
from hud import load_save, points_for, write_save
from main import click_damage, destroyed_asteroids, nuke_field
from player import Player
from shop import Shop, powerup_name_for_key


@pytest.fixture
def economy(tmp_path):
    """An Economy on a private save path (missing file → fresh defaults)."""
    return Economy(save_path=str(tmp_path / "game_save.json"))


@pytest.fixture
def shop(economy):
    return Shop(economy, Player(SCREEN_X, SCREEN_Y))


SCREEN_X = 640.0
SCREEN_Y = 360.0


def fund(economy, amount):
    """The test harness's hand on the ledger — real runs earn instead."""
    economy.credits = amount


# --- activation gating ------------------------------------------------------


@pytest.mark.parametrize("name", sorted(POWERUPS))
def test_activation_refuses_when_short_and_changes_nothing(economy, name):
    fund(economy, economy.powerup_price(name) - 0.01)
    uses_before = dict(economy.powerup_uses)
    assert economy.activate_powerup(name) is False
    assert economy.credits == economy.powerup_price(name) - 0.01
    assert economy.powerup_uses == uses_before
    assert economy.powerup_timers == {}


def test_unknown_powerup_name_is_refused(economy):
    fund(economy, 10_000)
    assert economy.activate_powerup("free_stuff") is False


def test_powerup_keys_come_from_the_table():
    assert powerup_name_for_key(pygame.K_7) == "gold_rush"
    assert powerup_name_for_key(pygame.K_8) == "nuke"
    assert powerup_name_for_key(pygame.K_9) == "overdrive"
    assert powerup_name_for_key(pygame.K_0) == "chrono"
    assert powerup_name_for_key(pygame.K_1) is None  # shop keys never collide


# --- activation pays, arms, and escalates ------------------------------------


def test_timed_activation_spends_and_arms_duration(economy):
    fund(economy, POWERUPS["gold_rush"]["cost"])
    assert economy.activate_powerup("gold_rush") is True
    assert economy.credits == 0
    assert economy.powerup_uses["gold_rush"] == 1
    assert economy.powerup_timers["gold_rush"] == POWERUPS["gold_rush"]["duration"]


def test_instant_nuke_pays_and_counts_without_arming(economy):
    fund(economy, POWERUPS["nuke"]["cost"])
    assert economy.activate_powerup("nuke") is True
    assert economy.powerup_uses["nuke"] == 1
    assert economy.powerup_timers == {}  # nothing to expire


def test_price_escalates_per_use(economy):
    fund(economy, 10_000)
    base = POWERUPS["nuke"]["cost"]
    for uses in range(3):
        assert economy.powerup_price("nuke") == pytest.approx(base * 1.25**uses)
        assert economy.activate_powerup("nuke") is True


def test_price_escalation_survives_save_roundtrip(economy):
    fund(economy, 10_000)
    assert economy.activate_powerup("gold_rush") is True
    assert economy.activate_powerup("gold_rush") is True
    economy.save()
    reloaded = Economy(save_path=economy.save_path)
    assert reloaded.powerup_uses["gold_rush"] == 2
    assert reloaded.powerup_price("gold_rush") == pytest.approx(
        POWERUPS["gold_rush"]["cost"] * POWERUP_PER_USE_PRICE_GROWTH**2
    )


def test_save_roundtrip_preserves_foreign_keys(economy):
    """F1's keys survive beside idle_powerup_uses — one file, no blind overwrite."""
    write_save(economy.save_path, {"high_score": 4242, "muted": True})
    fund(economy, 10_000)
    assert economy.activate_powerup("overdrive") is True
    economy.save()
    stored = json.loads(open(economy.save_path).read())
    assert stored["high_score"] == 4242
    assert stored["muted"] is True
    assert stored["idle_powerup_uses"]["overdrive"] == 1


def test_load_ignores_malformed_use_counts(economy):
    write_save(economy.save_path, {"idle_powerup_uses": {"nuke": -1, "overdrive": "many"}})
    reloaded = Economy(save_path=economy.save_path)
    assert reloaded.powerup_uses == {}


# --- expiry restores base values ---------------------------------------------


def test_expiry_restores_base_multipliers(economy):
    fund(economy, 10_000)
    assert economy.activate_powerup("overdrive") is True
    assert economy.activate_powerup("gold_rush") is True
    assert economy.overdrive_mult() == pytest.approx(10.0)
    assert economy.gold_rush_mult() == pytest.approx(5.0)
    economy.tick_powerups(POWERUPS["overdrive"]["duration"])
    assert economy.overdrive_mult() == pytest.approx(1.0)
    assert economy.gold_rush_mult() == pytest.approx(5.0)  # 15 s still running
    economy.tick_powerups(POWERUPS["gold_rush"]["duration"])
    assert economy.gold_rush_mult() == pytest.approx(1.0)
    assert economy.powerup_timers == {}


def test_chrono_scales_velocity_then_restores(economy):
    fund(economy, 10_000)
    assert economy.chrono_scale() == pytest.approx(1.0)
    assert economy.activate_powerup("chrono") is True
    assert economy.chrono_scale() == pytest.approx(0.5)
    economy.tick_powerups(POWERUPS["chrono"]["duration"])
    assert economy.chrono_scale() == pytest.approx(1.0)


def test_chrono_scale_moves_asteroids_at_half_speed():
    rock = Asteroid(0, 0, ASTEROID_MIN_RADIUS * 3)
    rock.velocity = pygame.Vector2(100, 0)
    Asteroid.speed_scale = 0.5
    try:
        rock.update(1.0)
        assert rock.position.x == pytest.approx(50)
    finally:
        Asteroid.speed_scale = 1.0  # never leak the dilation into other tests


def test_end_run_effects_clears_timers_but_keeps_use_counts(economy):
    fund(economy, 10_000)
    assert economy.activate_powerup("overdrive") is True
    economy.end_run_effects()
    assert economy.powerup_timers == {}
    assert economy.overdrive_mult() == pytest.approx(1.0)
    assert economy.powerup_uses["overdrive"] == 1  # the paid use is consumed


# --- effects observable through the game seams -------------------------------


def test_gold_rush_stacks_multiplicatively_with_income_upgrade(economy):
    fund(economy, 10_000)
    economy.levels["income"] = 2
    assert economy.activate_powerup("gold_rush") is True
    assert economy.income_multiplier() == pytest.approx(1.15**2 * 5.0)


def test_gold_rush_scales_the_mint(economy):
    fund(economy, 10_000)
    assert economy.activate_powerup("gold_rush") is True
    radius = ASTEROID_MIN_RADIUS * 3
    payout = economy.mint(radius)
    assert payout == pytest.approx(points_for(radius) * 5.0)


def test_overdrive_multiplies_click_damage(shop, economy):
    fund(economy, 10_000)
    base = click_damage(shop, economy)
    assert economy.activate_powerup("overdrive") is True
    assert click_damage(shop, economy) == pytest.approx(base * 10.0)
    economy.tick_powerups(POWERUPS["overdrive"]["duration"])
    assert click_damage(shop, economy) == pytest.approx(base)


def test_shop_routes_powerup_keys_through_the_ledger(shop, economy):
    fund(economy, POWERUPS["chrono"]["cost"])
    assert shop.handle_powerup_key(pygame.K_0) == "chrono"
    assert economy.powerup_timers["chrono"] == POWERUPS["chrono"]["duration"]
    fund(economy, 0)
    assert shop.handle_powerup_key(pygame.K_8) is None  # nuke unaffordable


# --- the nuke's single-payout invariant ---------------------------------------


def make_rock(x, y, radius):
    rock = Asteroid(x, y, radius)
    rock.velocity = pygame.Vector2(40, 0)
    return rock


def test_nuke_clears_the_field_and_pays_each_asteroid_exactly_once(economy):
    field = pygame.sprite.Group()
    radii = [ASTEROID_MIN_RADIUS * 4, ASTEROID_MIN_RADIUS * 3, ASTEROID_MIN_RADIUS]
    for index, radius in enumerate(radii):
        make_rock(100 + 100 * index, 100, radius).add(field)
    prev = set(field)  # the frame snapshot the loop's diff polls

    nuke_field(field)

    assert len(field) == 0  # the whole field died — no survivors, no free pass
    destroyed = destroyed_asteroids(prev, field)
    # One credit per rock on screen at nuke time: split children are new
    # sprites absent from prev, and children born and killed inside the same
    # call never appear in any frame snapshot — nothing pays twice.
    assert len(destroyed) == len(radii)
    expected = sum(points_for(radius) for radius in radii)
    paid = sum(economy.mint(rock.radius) for rock in destroyed)
    assert paid == pytest.approx(expected)