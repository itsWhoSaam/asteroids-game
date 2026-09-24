"""Tests for the idle ledger (economy.py): cost curve, minting, spending,
and the idle_* save merge through F1's read-modify-write loader."""

import json

import pytest

from constants import (
    ASTEROID_MIN_RADIUS,
    UPGRADE_COSTS,
)
from economy import Economy
from hud import points_for


@pytest.fixture
def economy(tmp_path):
    """An Economy on a private save path (missing file → fresh defaults)."""
    return Economy(save_path=str(tmp_path / "game_save.json"))


# --- cost curve -----------------------------------------------------------


def test_cost_curve_starts_at_base(economy):
    for name, (base, _growth) in UPGRADE_COSTS.items():
        assert economy.upgrade_cost(name) == base


@pytest.mark.parametrize("name", sorted(UPGRADE_COSTS))
def test_cost_curve_grows_exponentially(economy, name):
    _base, growth = UPGRADE_COSTS[name]
    for level in range(0, 5):
        economy.levels[name] = level
        here = economy.upgrade_cost(name)
        economy.levels[name] = level + 1
        there = economy.upgrade_cost(name)
        assert there / here == pytest.approx(growth)
    economy.levels[name] = 0


def test_cost_curve_closed_form(economy):
    economy.levels["drone"] = 3
    assert economy.upgrade_cost("drone") == pytest.approx(100.0 * 2.20**3)


# --- buying ---------------------------------------------------------------


def test_buy_refuses_when_short_and_changes_nothing(economy):
    _base, _growth = UPGRADE_COSTS["nanoblade"]
    economy.credits = 9.99
    assert economy.buy("nanoblade") is False
    assert economy.credits == 9.99
    assert economy.levels["nanoblade"] == 0


def test_buy_spends_and_levels_up(economy):
    economy.credits = 10.0  # nanoblade base cost
    assert economy.buy("nanoblade") is True
    assert economy.credits == 0.0
    assert economy.levels["nanoblade"] == 1
    assert economy.upgrade_cost("nanoblade") == pytest.approx(10.0 * 1.75)


# --- minting --------------------------------------------------------------


def test_mint_pays_points_table_at_flat_multiplier(economy):
    assert economy.income_multiplier() == 1.0
    payout = economy.mint(ASTEROID_MIN_RADIUS * 2)  # medium tier → 50
    assert payout == points_for(ASTEROID_MIN_RADIUS * 2) == 50
    assert economy.credits == 50.0


def test_mint_scales_through_the_income_multiplier_seam(economy):
    economy._income_multiplier = 2.5  # the seam the shop/powerup PRs raise
    payout = economy.mint(ASTEROID_MIN_RADIUS * 3)  # large tier → 20
    assert payout == 20 * 2.5
    assert economy.credits == 50.0


# --- persistence ----------------------------------------------------------


def test_save_roundtrip_preserves_f1_keys_beside_idle_keys(tmp_path, economy):
    path = tmp_path / "game_save.json"
    path.write_text(
        json.dumps(
            {
                "high_score": 4242,
                "muted": True,
                "future_feature_key": [1, 2, 3],
                "idle_credits": 55.0,
                "idle_levels": {"nanoblade": 2},
                "idle_last_seen": 1000.0,
            }
        )
    )

    loaded = Economy(save_path=str(path))
    assert loaded.credits == 55.0
    assert loaded.levels["nanoblade"] == 2

    loaded.mint(ASTEROID_MIN_RADIUS)  # +100 small-tier
    loaded.buy("nanoblade")  # level 2 cost 30.625 — affordable after the mint
    loaded.save()

    data = json.loads(path.read_text())
    assert data["high_score"] == 4242
    assert data["muted"] is True
    assert data["future_feature_key"] == [1, 2, 3]
    assert data["idle_credits"] == 155.0 - 30.625
    assert data["idle_levels"]["nanoblade"] == 3
    assert data["idle_last_seen"] >= 1000.0


def test_missing_save_is_a_fresh_install_without_warning(tmp_path, capsys):
    economy = Economy(save_path=str(tmp_path / "absent.json"))
    assert economy.credits == 0.0
    assert economy.last_seen == 0.0
    assert "[economy] warning:" not in capsys.readouterr().err


def test_garbage_save_falls_back_to_defaults_with_one_warning(tmp_path, capsys):
    path = tmp_path / "game_save.json"
    path.write_text("{this is not json")
    economy = Economy(save_path=str(path))
    assert economy.credits == 0.0
    assert economy.levels["drone"] == 0
    stderr = capsys.readouterr().err
    assert stderr.count("[economy] warning:") == 1


def test_nondict_save_root_is_corruption_too(tmp_path, capsys):
    path = tmp_path / "game_save.json"
    path.write_text("[1, 2, 3]")
    economy = Economy(save_path=str(path))
    assert economy.credits == 0.0
    assert capsys.readouterr().err.count("[economy] warning:") == 1


def test_malformed_idle_keys_are_ignored_field_by_field(tmp_path):
    path = tmp_path / "game_save.json"
    path.write_text(
        json.dumps(
            {
                "idle_credits": "plunder the vault",
                "idle_levels": {"nanoblade": "many", "drone": -5, "income": 2},
                "idle_last_seen": False,
            }
        )
    )
    economy = Economy(save_path=str(path))
    assert economy.credits == 0.0
    assert economy.levels["nanoblade"] == 0
    assert economy.levels["drone"] == 0  # negative levels are not trusted
    assert economy.levels["income"] == 2  # the one well-formed field loads
    assert economy.last_seen == 0.0
