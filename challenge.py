"""Daily seeded challenge (Tier 3): one fixed-seed run per UTC day.

The DAILY CHALLENGE toggles on the start/game-over flow (D, beside the
difficulty select). Launching a daily run points the asteroid field's
spawn path at an RNG seeded from the calendar date, so the spawn sequence
— timing, positions, velocities, sizes — is identical for everyone
playing that day. The run's best score persists per date in
game_save.json under one ``daily_best`` key, written through hud's
read-modify-write merge so every other feature's keys ride along — the
achievements precedent.

The determinism contract hangs off pure functions: the same date always
maps to the same seed, and a seed always builds an independent fresh RNG
(never a re-seeded shared stream), so a daily retry replays the same
spawns and a normal run's draws never see daily state.
"""

import datetime
import random

from constants import DAILY_SAVE_KEY
from hud import SAVE_PATH, load_save, write_save


def utc_today():
    """The challenge calendar: UTC, so the daily rollover is one event for
    everyone — not one per timezone."""
    return datetime.datetime.now(datetime.timezone.utc).date()


def daily_slug(day):
    """The per-date slot a daily best is stored under, pure: ISO YYYY-MM-DD."""
    return day.isoformat()


def daily_seed(day=None):
    """The run seed for a day, pure given the date: the YYYYMMDD integer.

    Same date, same seed, forever — this purity is the whole
    determinism contract. ``None`` reads today's UTC date.
    """
    if day is None:
        day = utc_today()
    return day.year * 10000 + day.month * 100 + day.day


def _daily_bests(path):
    """The per-date best dict from the save, defensively read: a missing,
    corrupt, or wrongly-typed key reads as empty — never a crash."""
    bests = load_save(path).get(DAILY_SAVE_KEY)
    return bests if isinstance(bests, dict) else {}


def load_daily_best(day=None, path=SAVE_PATH):
    """A date's persisted best, defensively read: absent or corrupt → 0."""
    best = _daily_bests(path).get(daily_slug(day or utc_today()))
    if isinstance(best, int) and not isinstance(best, bool):
        return best
    return 0


def record_daily_score(day, score, path=SAVE_PATH):
    """Offer a finished run's score to its date's best; True when it won.

    The write is the shared read-modify-write merge — re-read, update only
    the ``daily_best`` key, write back — so the high score, the idle
    ledger, and every other feature's keys survive untouched. A score of
    zero records nothing: an abandoned run is not a best.
    """
    if score <= 0:
        return False
    slug = daily_slug(day)
    bests = _daily_bests(path)
    previous = bests.get(slug, 0)
    if not (isinstance(previous, int) and not isinstance(previous, bool)):
        previous = 0
    if score <= previous:
        return False
    # A shallow copy keeps the writer honest: only this module's key moves.
    save = load_save(path)
    save[DAILY_SAVE_KEY] = {**bests, slug: score}
    write_save(path, save)
    return True
