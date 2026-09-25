"""Run-scoped statistics (run-stats PR): the counters behind the end-of-run
summary.

The counters are run-scoped by design — never saved, never read back: a
restart starts a fresh accounting, and a save file never learns a stats key.
The single instance lives on Game (the single owner of run state), which
also injects it into the player; the destruction poll, the collision sweep,
and the wave harness record against it. Every recording method is a plain
counter bump driven by the instrumentation sites, so purity tests can drive
a bare instance with synthetic events.
"""

from constants import ASTEROID_MIN_RADIUS

# Size-tier names, matching the points_for banding (hud.py): small 1x,
# medium 2x, large 3x and up.
TIERS = ("small", "medium", "large")

# Credit attribution at the mint poll: a rock's killer decides which bucket
# its payout lands in. "click" is a rock the player clicked apart; "idle" is
# every other destruction — shots (player or drone turrets) and nukes — the
# idle economy paying the ledger for the field clearing itself.
SOURCE_CLICK = "click"
SOURCE_IDLE = "idle"


def tier_for(radius):
    """The size tier of a rock radius: "small", "medium", or "large".

    Pure, and the same banding points_for() pays on — small 1x
    ASTEROID_MIN_RADIUS, medium 2x, large 3x and up — so the summary's
    tier counts and the score table can never disagree about a rock.
    """
    if radius >= ASTEROID_MIN_RADIUS * 3:
        return "large"
    if radius >= ASTEROID_MIN_RADIUS * 2:
        return "medium"
    return "small"


class RunStats:
    """The per-run counters the game-over summary reports.

    reset() zeroes in place — Game.restart may never rebind the instance,
    because the player records against the same object it was handed.
    """

    def __init__(self):
        self.shots_fired = 0
        self.shots_hit = 0
        self.destroyed = {tier: 0 for tier in TIERS}
        self.waves_survived = 0
        self.credits_idle = 0.0
        self.credits_click = 0.0

    def record_shot(self):
        """One bullet left the ship (a TRIPLE volley is three)."""
        self.shots_fired += 1

    def record_hit(self):
        """One player shot connected with a live asteroid."""
        self.shots_hit += 1

    def record_destroyed(self, radius):
        """One destroyed rock, banded to its size tier — every destruction
        source pays here through the mint poll's diff."""
        self.destroyed[tier_for(radius)] += 1

    def record_wave_cleared(self):
        """One wave cleared. Dying mid-wave counts the clears, not the
        wave you died on."""
        self.waves_survived += 1

    def record_credits(self, amount, source):
        """The mint poll's payout, bucketed by kill source: a rock the
        player clicked apart pays "click", everything else pays "idle"."""
        if source == SOURCE_CLICK:
            self.credits_click += amount
        else:
            self.credits_idle += amount

    @property
    def credits_earned(self):
        """Everything the ledger paid this run: idle plus click."""
        return self.credits_idle + self.credits_click

    def accuracy(self):
        """Hit fraction of fired shots, or None when no shot was fired —
        undefined, not zero, so a passive run is not a 0% one."""
        if self.shots_fired == 0:
            return None
        return self.shots_hit / self.shots_fired

    def reset(self):
        """Zero every counter, in place.

        In place on purpose: Game hands this instance to the player at
        construction, so restart hooks must never rebind — a fresh object
        would leave the ship recording into a dead run's counters.
        """
        self.shots_fired = 0
        self.shots_hit = 0
        self.destroyed = {tier: 0 for tier in TIERS}
        self.waves_survived = 0
        self.credits_idle = 0.0
        self.credits_click = 0.0

    def summary_lines(self):
        """The summary rows, pure: the game-over block renders exactly
        these, and the tests pin their wording. Whole credits render as
        ints, matching draw_credits."""
        if self.shots_fired > 0:
            pct = round(100 * self.shots_hit / self.shots_fired)
            shots = f"Shots: {self.shots_hit}/{self.shots_fired} hit ({pct}%)"
        else:
            shots = "Shots: 0/0 hit"
        rocks = (
            f"Rocks destroyed: {self.destroyed['small']} small, "
            f"{self.destroyed['medium']} medium, {self.destroyed['large']} large"
        )
        waves = f"Waves survived: {self.waves_survived}"
        credits = (
            f"Credits earned: {int(self.credits_earned)}"
            f" (idle {int(self.credits_idle)}, click {int(self.credits_click)})"
        )
        return [shots, rocks, waves, credits]
