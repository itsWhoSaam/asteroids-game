"""Persisted achievements + the queued toast banner (Tier 2).

Five lifetime awards — first nuke used, wave 5 reached, 10,000 points in one
run, first drone deployed, high score beaten — evaluated by a PURE function
over a per-frame EventStats snapshot. The unlocked set persists in
game_save.json as the ``achievements`` key, written through hud's
read-modify-write merge so the idle_* keys and the high score ride along
untouched — the same contract Economy.save rides.

The snapshot builder only reads the live owners (Game for run state, Economy
for the lifetime counters) and keeps no state of its own, so restart hooks
need nothing here: the unlocked set is lifetime state (deliberately survives
restarts), and the evaluation input is re-derived every frame. Each unlock
persists immediately, then queues a toast — one at a time, FIFO, expiring on
the dt-timer template (FloatingText is the house pattern: no wall-clock
calls, so tests and headless runs step it deterministically).
"""

from typing import Callable, NamedTuple

import pygame

from comicfx import cached_text, shared_font
from constants import (
    ACHIEVEMENT_SCORE_THRESHOLD,
    ACHIEVEMENT_WAVE_THRESHOLD,
    PANEL_PAD_X,
    PANEL_PAD_Y,
    PALETTE,
    SCREEN_WIDTH,
    TOAST_FONT_SIZE,
    TOAST_SEAT_Y,
    TOAST_SLIDE_SECONDS,
    TOAST_SECONDS,
)
from hud import SAVE_PATH, load_save, panel_for, write_save
from logger import log_event


class EventStats(NamedTuple):
    """The per-frame stats snapshot achievements evaluate against.

    One row per award trigger: the run score and wave from Game, the
    lifetime nuke uses and drone level from Economy (both already
    persisted by the idle ledger), and the run's high-score-beaten flag.
    Pure data — a test constructs it directly.
    """

    score: float
    wave: int
    nuke_uses: int
    drone_level: int
    high_score_beaten: bool


def event_stats_from(game, economy):
    """Snapshot the live owners into an EventStats.

    Reads only — never mutates — so the per-frame evaluation cannot disturb
    the run or the ledger it reads.
    """
    return EventStats(
        score=game.score,
        wave=game.wave,
        nuke_uses=economy.powerup_uses.get("nuke", 0),
        drone_level=economy.levels["drone"],
        high_score_beaten=game.new_high,
    )


class AchievementDef(NamedTuple):
    """One award: its save id, its toast title, and its pure trigger."""

    id: str
    title: str
    met: Callable[[EventStats], bool]


# The awards, in the order they queue when several fire on one frame —
# tuple order is toast order, so the table is the FIFO's source of truth.
ACHIEVEMENTS = (
    AchievementDef(
        "first_nuke",
        "FIRST NUKE",
        lambda stats: stats.nuke_uses >= 1,
    ),
    AchievementDef(
        "wave_5",
        f"WAVE {ACHIEVEMENT_WAVE_THRESHOLD}",
        lambda stats: stats.wave >= ACHIEVEMENT_WAVE_THRESHOLD,
    ),
    AchievementDef(
        "score_10000",
        f"SCORE {ACHIEVEMENT_SCORE_THRESHOLD:,}",
        lambda stats: stats.score >= ACHIEVEMENT_SCORE_THRESHOLD,
    ),
    AchievementDef(
        "first_drone",
        "FIRST DRONE",
        lambda stats: stats.drone_level >= 1,
    ),
    AchievementDef(
        "high_score_beaten",
        "HIGH SCORE BEATEN",
        lambda stats: stats.high_score_beaten,
    ),
)

ACHIEVEMENTS_BY_ID = {defn.id: defn for defn in ACHIEVEMENTS}


def evaluate_achievements(unlocked, stats):
    """The awards `stats` newly earns, in table order.

    Pure threshold evaluation over the EventStats snapshot: an id already in
    `unlocked` can never re-fire, so calling every frame is free and each
    award provably fires exactly once per lifetime.
    """
    return [
        defn
        for defn in ACHIEVEMENTS
        if defn.id not in unlocked and defn.met(stats)
    ]


def load_unlocked(save_path=SAVE_PATH):
    """The persisted unlocked ids, or an empty set for a fresh install.

    Reads through the shared loader's whole-dict merge; a missing, corrupt,
    or foreign `achievements` key falls back to empty — never a crash, and
    never a write (the read side of the read-modify-write contract).
    """
    ids = load_save(save_path).get("achievements")
    if not isinstance(ids, list):
        return set()
    return {
        aid for aid in ids if isinstance(aid, str) and aid in ACHIEVEMENTS_BY_ID
    }


def save_unlocked(save_path, unlocked):
    """Merge the unlocked ids into the shared save file.

    Read-modify-write like Economy.save: the loader returns the whole dict,
    only `achievements` changes here, and every other feature's keys ride
    along untouched. A fresh-dict write here would erase idle_* — the
    cross-feature tests pin that tripwire.
    """
    data = load_save(save_path)
    data["achievements"] = sorted(unlocked)
    write_save(save_path, data)


def toast_y(elapsed, duration, panel_height):
    """The toast's top y at `elapsed` of `duration` — pure slide geometry.

    The panel rises from fully above the screen (top y -panel_height) to its
    seat TOAST_SEAT_Y over TOAST_SLIDE_SECONDS, holds, and mirrors the slide
    out over the final TOAST_SLIDE_SECONDS; outside [0, duration] it is
    hidden. Position animation only — the surface itself never fades, so
    dummy drivers see an ordinary opaque blit.
    """
    travel = TOAST_SEAT_Y + panel_height
    if elapsed <= 0.0 or elapsed >= duration:
        return -panel_height
    if elapsed < TOAST_SLIDE_SECONDS:
        return -panel_height + travel * (elapsed / TOAST_SLIDE_SECONDS)
    if elapsed > duration - TOAST_SLIDE_SECONDS:
        return -panel_height + travel * ((duration - elapsed) / TOAST_SLIDE_SECONDS)
    return TOAST_SEAT_Y


class ToastQueue:
    """FIFO toasts, one visible at a time, dt-timer expiry (FloatingText).

    A queued toast waits until the seated one expires, then steps into the
    seat with a fresh clock — the queue never reorders, so a multi-unlock
    frame announces in the achievement table's order.
    """

    def __init__(self, duration=TOAST_SECONDS):
        self.duration = duration
        self.queue = []
        self.current = None
        self.elapsed = 0.0

    def show(self, title):
        """Queue a toast; it seats when the current one clears out."""
        self.queue.append(title)

    @property
    def visible(self):
        return self.current is not None

    def update(self, dt):
        """Advance the dt-timer: expire a seated toast, then hand the seat
        to the next queued one. No wall-clock calls — pure dt stepping."""
        if self.current is not None:
            self.elapsed += dt
            if self.elapsed >= self.duration:
                self.current = None
                self.elapsed = 0.0
        if self.current is None and self.queue:
            self.current = self.queue.pop(0)
            self.elapsed = 0.0

    def draw(self, screen):
        """The seated toast: a caption panel in the V5 family at the pure
        slide position, top-center — under the game-over overlay and the
        wave banner, both of which own lower or center seats."""
        if not self.visible:
            return
        text = f"ACHIEVEMENT — {self.current}"
        font = shared_font(TOAST_FONT_SIZE)
        surface = cached_text(text, PALETTE["hud_ink"], TOAST_FONT_SIZE)
        # Panel widths bucket to 32px (draw_game_over's precedent) so the
        # handful of titles reuse cached panels instead of growing them.
        width = -(-(font.size(text)[0] + 2 * PANEL_PAD_X) // 32) * 32
        panel = panel_for(width, font.get_height() + 2 * PANEL_PAD_Y)
        y = toast_y(self.elapsed, self.duration, panel.get_height())
        rect = panel.get_rect(midtop=(SCREEN_WIDTH / 2, y))
        screen.blit(panel, rect)
        screen.blit(surface, surface.get_rect(center=rect.center))


class Achievements:
    """The unlocked set plus its toast queue — the main loop's handle.

    Persistence rides the save merge on every unlock; evaluation is
    idempotent per lifetime, so main() calls it every unpaused frame for
    free. Not run state: both restart hooks are untouched by design — the
    unlocked set is lifetime (saved), and the toast queue is ephemeral UI
    like the wave banner, which also rides across a restart.
    """

    def __init__(self, save_path=SAVE_PATH):
        self.save_path = save_path
        self.unlocked = load_unlocked(save_path)
        self.toasts = ToastQueue()

    def evaluate(self, stats):
        """Unlock and announce everything `stats` newly earns, in table
        order. Returns the newly unlocked defs (empty most frames)."""
        newly = evaluate_achievements(self.unlocked, stats)
        for defn in newly:
            self.unlock(defn)
        return newly

    def unlock(self, defn):
        """Persist one award through the save merge, log it, queue its toast."""
        self.unlocked.add(defn.id)
        save_unlocked(self.save_path, self.unlocked)
        log_event("achievement_unlocked", achievement=defn.id)
        self.toasts.show(defn.title)

    def update(self, dt):
        """Age the toast queue — main ticks it on unpaused frames only, the
        offline-banner precedent: a frozen frame fades no UI timers."""
        self.toasts.update(dt)

    def draw(self, screen):
        self.toasts.draw(screen)
