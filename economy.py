"""The idle ledger: credits, upgrade levels, and their persistence.

Economy is the ONLY writer of the ``idle_*`` keys in game_save.json — every
mint, purchase, and autosave flows through this module. Writes merge into
hud's read-modify-write loader output, so F1's ``high_score``/``muted`` keys
(and any future feature's keys) ride along untouched. A missing file is a
fresh install; a corrupt or unreadable one falls back to defaults with one
printed warning. No economy error may ever kill the game loop — the ledger
fails safe.
"""

import json
import sys
import time

from constants import UPGRADE_COSTS
from hud import SAVE_PATH, load_save, points_for, write_save


def _corrupt_reason(path):
    """Why the save can't be used as-is, or None when it's fine.

    A missing file is a fresh install, not corruption — no warning for it.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except ValueError as exc:
        return f"invalid JSON ({exc})"
    except OSError as exc:
        return f"unreadable ({exc})"
    if not isinstance(data, dict):
        return "save root is not a JSON object"
    return None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Economy:
    """Credits, upgrade levels, and every mutation of them.

    Loads its ``idle_*`` state through F1's loader at construction (the same
    seam Score uses) and merges back through it on save, so both features
    can write the shared file without ever erasing each other.
    """

    def __init__(self, save_path=SAVE_PATH):
        self.save_path = save_path
        self.credits = 0.0
        self.levels = {name: 0 for name in UPGRADE_COSTS}
        self.last_seen = 0.0
        # Income-multiplier seam: the income upgrade (shop PR) and the
        # gold-rush powerup scale payouts through income_multiplier();
        # the core pays flat 1.0.
        self._income_multiplier = 1.0
        self._load_state()

    # --- ledger reads -----------------------------------------------------

    def income_multiplier(self):
        """Scale factor applied to every mint; flat 1.0 until the shop PR."""
        return self._income_multiplier

    def upgrade_cost(self, name):
        """Exponential curve: cost(n) = base × growth**n at the current level."""
        base, growth = UPGRADE_COSTS[name]
        return base * growth ** self.levels[name]

    # --- ledger writes ----------------------------------------------------

    def mint(self, radius):
        """Pay out one destroyed asteroid and return the amount paid.

        The payout scales the sibling F1 points table by the income
        multiplier, so income and progression share one source of truth.
        """
        payout = points_for(radius) * self.income_multiplier()
        self.credits += payout
        return payout

    def buy(self, name):
        """Spend one level of ``name``; False (and no change) when short."""
        cost = self.upgrade_cost(name)
        if self.credits < cost:
            return False
        self.credits -= cost
        self.levels[name] += 1
        return True

    # --- persistence ------------------------------------------------------

    def save(self):
        """Merge idle_* keys into the shared save file, preserving the rest.

        Re-reads through the loader on every write (read-modify-write), so
        F1's high-score writes and any other feature's keys survive ours.
        """
        data = load_save(self.save_path)
        data["idle_credits"] = self.credits
        data["idle_levels"] = dict(self.levels)
        data["idle_last_seen"] = time.time()
        write_save(self.save_path, data)

    def _load_state(self):
        reason = _corrupt_reason(self.save_path)
        if reason is not None:
            print(
                f"[economy] warning: {self.save_path} unusable ({reason}); "
                "starting the idle ledger from defaults",
                file=sys.stderr,
            )
        data = load_save(self.save_path)
        credits = data.get("idle_credits")
        if _is_number(credits):
            self.credits = float(credits)
        levels = data.get("idle_levels")
        if isinstance(levels, dict):
            for name in self.levels:
                level = levels.get(name)
                if isinstance(level, int) and not isinstance(level, bool) and level >= 0:
                    self.levels[name] = level
        seen = data.get("idle_last_seen")
        if _is_number(seen):
            self.last_seen = float(seen)
