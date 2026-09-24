"""Balance-pass gates (integration pass): the two playtest measurements,
run headlessly through the simulation harness in tests/_balance_sim.py.

The ten-minute out-scaling measurement lives in the harness's standalone
report (`uv run python -m tests._balance_sim`), where it prints the
per-minute curve for the PR body — its gate needs the full horizon to be
meaningful, and a ten-minute sim has no business inside the fast unit
suite. These tests pin the two gates that do fit: the fresh-save
onboarding budget and the nuke pipeline end to end, on a fixed seed so
the numbers are reproducible.
"""

from constants import POWERUPS
from tests._balance_sim import run_nuke_scenario, run_session

# The brief's budget: a fresh save affords the first Nanoblade level
# (base cost 10 credits) within ~30 seconds of shooting.
NANOBLADE_ONBOARDING_BUDGET_S = 30.0

# One full session's worth of sim-seconds above the budget — long enough
# that a failing economy shows up, short enough to stay fast.
PROBE_SECONDS = 35.0


def test_first_nanoblade_affordable_within_30s_of_shooting(tmp_path):
    """Shooting only, fresh save: the first kill's payout (20–100 credits
    through the points table) covers the 10-credit first level well inside
    the budget. Measured 7.3s on the current constants."""
    stats = run_session(
        PROBE_SECONDS,
        save_path=str(tmp_path / "game_save.json"),
        clicks_per_second=0,  # shooting only — the brief's onboarding gate
    )
    assert stats.afford_nanoblade_s is not None, "never afforded the first level"
    assert stats.afford_nanoblade_s <= NANOBLADE_ONBOARDING_BUDGET_S


def test_nuke_clears_field_and_pays_every_rock_exactly_once(tmp_path):
    """Bounded end-to-end: a shop purchase grows the drone fleet, the
    shared pipeline mints for drone kills, and one nuke activation (key 8)
    empties the field and pays each on-screen rock exactly once — at the
    escalating per-use price, through the ordinary destruction diff."""
    result = run_nuke_scenario(save_path=str(tmp_path / "game_save.json"))

    assert result["nuke_price_paid"] == POWERUPS["nuke"]["cost"]
    assert result["field_empty"], "the nuke left rocks alive"
    assert result["pipeline_income_4s"] > 0, "drone/click income never minted"
    assert result["paid_exactly_once"], (
        f"nuke payout {result['nuke_payout']} != expected "
        f"{result['expected_payout']} for tiers {result['rock_tiers']}"
    )
