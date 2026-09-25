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

from constants import (
    INCOME_MULT_PER_LEVEL,
    OFFLINE_CAP_SECONDS,
    OFFLINE_RATE,
    POWERUP_GOLD_RUSH_MULT,
    POWERUP_OVERDRIVE_MULT,
    POWERUP_PER_USE_PRICE_GROWTH,
    POWERUP_CHRONO_SLOW,
    POWERUPS,
    UPGRADE_COSTS,
)
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
        # Bought powerups (insane-powerups PR): activation counts drive the
        # escalating per-use price; active timers tick down on dt.
        self.powerup_uses = {}
        self.powerup_timers = {}
        # Income-multiplier seam: the income upgrade (shop PR) and the
        # gold-rush powerup scale payouts through income_multiplier();
        # the core pays flat 1.0.
        self._income_multiplier = 1.0
        self._load_state()

    # --- ledger reads -----------------------------------------------------

    def income_multiplier(self):
        """Scale factor applied to every mint.

        The Income upgrade compounds per level (the shop PR buys it); an
        active Gold Rush multiplies the whole seam, stacking with the
        upgrade — riding the one hook this seam always promised.
        """
        return (
            self._income_multiplier
            * INCOME_MULT_PER_LEVEL ** self.levels["income"]
            * self.gold_rush_mult()
        )

    def upgrade_cost(self, name):
        """Exponential curve: cost(n) = base × growth**n at the current level."""
        base, growth = UPGRADE_COSTS[name]
        return base * growth ** self.levels[name]

    def powerup_price(self, name):
        """Escalating per-use price: base cost × 1.25 ** uses so far."""
        base = POWERUPS[name]["cost"]
        return base * POWERUP_PER_USE_PRICE_GROWTH ** self.powerup_uses.get(name, 0)

    # --- ledger writes ----------------------------------------------------

    def mint(self, radius):
        """Pay out one destroyed asteroid and return the amount paid.

        The payout scales the sibling F1 points table by the income
        multiplier, so income and progression share one source of truth.
        """
        payout = points_for(radius) * self.income_multiplier()
        self.credits += payout
        return payout

    def grant_milestone(self, amount):
        """Pay a flat milestone bonus (wave rewards) and return the amount.

        Deliberately no income multiplier, unlike a mint: the banner
        announces the exact number the ledger receives, so scaling here
        would make the announcement a lie."""
        self.credits += amount
        return amount

    def buy(self, name):
        """Spend one level of ``name``; False (and no change) when short."""
        cost = self.upgrade_cost(name)
        if self.credits < cost:
            return False
        self.credits -= cost
        self.levels[name] += 1
        return True

    # --- bought powerups ---------------------------------------------------

    def activate_powerup(self, name):
        """Buy one activation of ``name``; False (and no change) when short.

        The use count is what escalates the next price; timed effects
        (re)arm their duration from the constants table, instant ones —
        the nuke — pay and count without arming anything.
        """
        if name not in POWERUPS:
            return False
        price = self.powerup_price(name)
        if self.credits < price:
            return False
        self.credits -= price
        self.powerup_uses[name] = self.powerup_uses.get(name, 0) + 1
        duration = POWERUPS[name]["duration"]
        if duration > 0:
            self.powerup_timers[name] = duration
        return True

    def tick_powerups(self, dt):
        """Expire timed effects on the repo's dt-timer pattern: decrement
        each clock, drop the name when it runs out. Every effect reads its
        multiplier live (below), so expiry restores base values by itself —
        there is nothing to undo."""
        for name, remaining in list(self.powerup_timers.items()):
            remaining -= dt
            if remaining > 0:
                self.powerup_timers[name] = remaining
            else:
                del self.powerup_timers[name]

    def end_run_effects(self):
        """End every active timed effect — the bought-effect counterpart to
        Player.clear_powerups on a full restart: the paid use is consumed,
        the new run starts clean."""
        self.powerup_timers = {}

    def overdrive_mult(self):
        """Click chip-damage factor: ×10 while Overdrive runs, else 1.0.

        Shots never route here — they keep their instant-kill split()."""
        return POWERUP_OVERDRIVE_MULT if "overdrive" in self.powerup_timers else 1.0

    def gold_rush_mult(self):
        """Mint factor: ×5 while Gold Rush runs, else 1.0."""
        return POWERUP_GOLD_RUSH_MULT if "gold_rush" in self.powerup_timers else 1.0

    def chrono_scale(self):
        """Asteroid velocity factor: ×0.5 while Chrono runs, else 1.0."""
        return POWERUP_CHRONO_SLOW if "chrono" in self.powerup_timers else 1.0

    def active_powerups(self):
        """Timed effects still running, as (title, remaining seconds) —
        the HUD indicator's content, soonest-to-expire first."""
        return sorted(
            (POWERUPS[name]["title"], remaining)
            for name, remaining in self.powerup_timers.items()
        )

    # --- offline earnings -------------------------------------------------

    def apply_offline(self, elapsed_s, drone_dps):
        """Capped idle payout for time away — the boot grant's math.

        ``drone_dps`` is the fleet's estimated credits/second (see
        drones.drone_dps): one instant-kill shot per DRONE_FIRE_INTERVAL_S
        at the DRONE_CREDITS_PER_SHOT estimate. Time beyond
        OFFLINE_CAP_SECONDS pays nothing extra and OFFLINE_RATE halves the
        whole grant — drones work overtime at half pay. Negative elapsed
        (clock skew) clamps to zero; the ledger only ever grows here.
        """
        capped = min(max(elapsed_s, 0.0), OFFLINE_CAP_SECONDS)
        earned = drone_dps * capped * OFFLINE_RATE
        self.credits += earned
        return earned

    def claim_offline(self, drone_dps, now=None):
        """The once-per-boot grant: elapsed resolved from idle_last_seen.

        A missing stamp (fresh install, or a save from before the drones
        PR — last_seen stays 0.0) grants nothing and raises nothing. A
        granted claim re-stamps last_seen so the in-session autosave can't
        double-pay the same window; the next save() persists the stamp.
        """
        if now is None:
            now = time.time()
        if self.last_seen <= 0.0:
            return 0.0
        earned = self.apply_offline(now - self.last_seen, drone_dps)
        if earned > 0:
            self.last_seen = now
        return earned

    # --- persistence ------------------------------------------------------

    def save(self):
        """Merge idle_* keys into the shared save file, preserving the rest.

        Re-reads through the loader on every write (read-modify-write), so
        F1's high-score writes and any other feature's keys survive ours.
        """
        data = load_save(self.save_path)
        data["idle_credits"] = self.credits
        data["idle_levels"] = dict(self.levels)
        data["idle_powerup_uses"] = dict(self.powerup_uses)
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
        uses = data.get("idle_powerup_uses")
        if isinstance(uses, dict):
            for name in POWERUPS:
                count = uses.get(name)
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    self.powerup_uses[name] = count
