"""Score tracking, persistent high score, and the HUD overlays (engagement F1).

F2's Game object absorbed the Score seam: it owns the run score and delegates
to Score for high-score persistence. main() renders whatever draw_hud and
draw_game_over draw.
"""

import json
import sys

import pygame

from constants import (
    ASTEROID_MIN_RADIUS,
    BOSS_BAR_FILL_COLOR,
    BOSS_BAR_HEIGHT,
    BOSS_BAR_TRACK_COLOR,
    BOSS_BAR_WIDTH,
    BOSS_BAR_Y,
    COMBO_BREAK_MIN_CHAIN,
    COMBO_CAP,
    COMBO_COLOR,
    COMBO_MILESTONES,
    COMBO_STEP,
    COMBO_WINDOW_SECONDS,
    DASH_COOLING_COLOR,
    GAME_OVER_FONT_SIZE,
    GAME_OVER_LINE_STEP,
    HUD_COLOR,
    HUD_FONT_SIZE,
    HUD_LINE_STEP,
    HUD_MARGIN,
    SCORE_LARGE,
    SCORE_MEDIUM,
    SCORE_SMALL,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    WAVE_BANNER_SECONDS,
)
from logger import log_event
import sound

SAVE_PATH = "game_save.json"

# Missing or corrupt save data falls back to these, never a crash.
DEFAULT_SAVE = {"high_score": 0, "muted": False}


def points_for(radius):
    """Points for destroying an asteroid, by size tier.

    Tiers are multiples of ASTEROID_MIN_RADIUS — small 1x, medium 2x, large
    3x and up — and smaller rocks pay more: 100 / 50 / 20. The large band
    opens at 3x because the field's biggest spawn is 3x (ASTEROID_KINDS = 3);
    the spec's 4x large anchor sits inside the same band.
    """
    if radius >= ASTEROID_MIN_RADIUS * 3:
        return SCORE_LARGE
    if radius >= ASTEROID_MIN_RADIUS * 2:
        return SCORE_MEDIUM
    return SCORE_SMALL


def load_save(path=SAVE_PATH):
    """Load the whole save file; any problem falls back to defaults, never a crash.

    Read-modify-write contract: unknown keys ride along untouched — this
    module manages only high_score and muted, so later features (the
    idle-economy follow-up) own their fields without our writes erasing them.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULT_SAVE)
    if not isinstance(data, dict):
        return dict(DEFAULT_SAVE)
    save = dict(data)
    high = save.get("high_score")
    if not (isinstance(high, int) and not isinstance(high, bool)):
        save["high_score"] = DEFAULT_SAVE["high_score"]
    muted = save.get("muted")
    if not isinstance(muted, bool):
        save["muted"] = DEFAULT_SAVE["muted"]
    return save


def write_save(path, save):
    """Persist the save dict; I/O failure warns like logger.py instead of crashing."""
    try:
        with open(path, "w") as f:
            json.dump(save, f)
    except OSError as exc:
        print(f"[hud] warning: could not write {path}: {exc}", file=sys.stderr)


class Score:
    """Current run score plus the persistent high score.

    F2's Game object owns this instance and surfaces its state; the sweep
    reaches it through Game.add_score.
    """

    def __init__(self, save_path=SAVE_PATH):
        self.save_path = save_path
        # The whole save dict is kept so unknown keys from other features
        # survive our writes; only the two managed keys are updated.
        self._data = load_save(save_path)
        self.current = 0
        self.high = self._data["high_score"]
        self.muted = self._data["muted"]
        self._beaten = False

    def add_score(self, points):
        """Add points and persist a newly beaten high score.

        The milestone event fires once, at the first crossing. While beaten,
        the high score tracks the current one and every add rewrites the save:
        F1 has no game-over hook yet, so a hard exit must not lose the record.
        """
        self.current += points
        if self.current <= self.high:
            return
        if not self._beaten:
            self._beaten = True
            log_event("high_score_beaten", score=self.current)
        self.high = self.current
        self._data["high_score"] = self.high
        self._data["muted"] = self.muted
        write_save(self.save_path, self._data)

    def set_muted(self, muted):
        """Persist the mute preference (F6) through the save loader: the
        whole save dict is written, so unknown keys still ride along."""
        self.muted = muted
        self._data["muted"] = muted
        write_save(self.save_path, self._data)
        return muted

    @property
    def beaten(self):
        """True once this run has beaten the persisted high score."""
        return self._beaten

    def reset(self):
        """Start a fresh run: score to zero, re-arm the beaten flag.

        The high score itself is untouched — it was persisted on every
        crossing, so a restart cannot lose the record.
        """
        self.current = 0
        self._beaten = False


def combo_multiplier(chain, step=COMBO_STEP, cap=COMBO_CAP):
    """Pure: points multiplier for a chain of `chain` shot kills.

    The first kill pays face value; each further link inside the window adds
    `step`, capped. 0.25/step means x2 at chain 5 — the milestone tier."""
    if chain <= 1:
        return 1.0
    return min(1.0 + step * (chain - 1), cap)


class ComboMeter:
    """The shot-kill chain (insanity core): score-only, never credits.

    register_kill extends the chain and re-arms the window; tick drains the
    window on the dt the simulation runs on (the house dt-timer pattern, so
    tests step it and hit-stop holds it). The run's top chain and best
    multiplier survive breaks — they are the game-over stat lines.
    """

    def __init__(self):
        self.chain = 0
        self.window = 0.0
        self.top = 0  # best chain this run — the game-over stat
        self.best_multiplier = 1.0
        self._milestone_hit = set()

    @property
    def active(self):
        return self.chain > 0

    def register_kill(self):
        """A rock died to player-or-drone fire: extend the chain and return
        it. Milestones log once per run — a re-climbed tier stays silent."""
        self.chain += 1
        self.window = COMBO_WINDOW_SECONDS
        self.top = max(self.top, self.chain)
        self.best_multiplier = max(self.best_multiplier, combo_multiplier(self.chain))
        if self.chain in COMBO_MILESTONES and self.chain not in self._milestone_hit:
            self._milestone_hit.add(self.chain)
            log_event("combo_milestone", chain=self.chain)
        return self.chain

    def tick(self, dt):
        """Drain the window; expiry breaks the chain (the house dt-timer)."""
        if self.window <= 0:
            return
        self.window -= dt
        if self.window <= 0:
            self.break_chain()

    def break_chain(self):
        """Drop the chain. Only a chain worth naming (>= the min) logs and
        sighs — a two-kill stumble is noise, not an event."""
        if self.chain >= COMBO_BREAK_MIN_CHAIN:
            log_event("combo_break", chain=self.chain)
            sound.play(sound.SFX_COMBO_BREAK)
        self.chain = 0
        self.window = 0.0

    def reset(self):
        """Full-restart hook: every counter, including the run stats."""
        self.__init__()


_hud_font_cache = None


def hud_font():
    """Lazily built HUD font; pygame.font is ready once pygame.init() ran."""
    global _hud_font_cache
    if _hud_font_cache is None:
        _hud_font_cache = pygame.font.Font(None, HUD_FONT_SIZE)
    return _hud_font_cache


def draw_hud(screen, score, lives=0, wave=0, muted=False, combo=None,
             dash_timer=None):
    """Draw the HUD top-left. Score always shows; the lives and wave slots
    stay hidden while zero — F2 and F3 feed them. While playback is muted
    (F6) a small MUTED tag sits top-right — the only visible feedback
    silence ever gives.

    Insanity core slots, passed only while a run is live: the combo readout
    sits directly under the wave slot, amber and dimming as its window
    drains; the dash slot below shows ready or the cooling seconds."""
    lines = [f"Score: {score}"]
    if lives:
        lines.append(f"Lives: {lives}")
    if wave:
        lines.append(f"Wave: {wave}")
    font = hud_font()
    for row, text in enumerate(lines):
        surface = font.render(text, True, HUD_COLOR)
        screen.blit(surface, (HUD_MARGIN, HUD_MARGIN + row * HUD_LINE_STEP))
    # The insanity slots stack under whatever the basics drew (combo
    # under the wave slot); main passes them only during play.
    slot_row = len(lines)
    if combo is not None and combo.active:
        remaining = max(combo.window, 0.0)
        surface = font.render(
            f"COMBO x{combo.chain} ({remaining:.1f})", True, COMBO_COLOR
        )
        # Amber, dimming as the window drains — the chain visibly dying
        # with its clock, the same alpha-fade idiom as WaveBanner.
        surface.set_alpha(int(255 * remaining / COMBO_WINDOW_SECONDS))
        screen.blit(surface, (HUD_MARGIN, HUD_MARGIN + slot_row * HUD_LINE_STEP))
    if dash_timer is not None:
        if dash_timer > 0:
            text, color = f"DASH {dash_timer:.1f}", DASH_COOLING_COLOR
        else:
            text, color = "DASH READY", HUD_COLOR
        surface = font.render(text, True, color)
        screen.blit(
            surface, (HUD_MARGIN, HUD_MARGIN + (slot_row + 1) * HUD_LINE_STEP)
        )
    if muted:
        surface = font.render("MUTED", True, HUD_COLOR)
        rect = surface.get_rect(topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN))
        screen.blit(surface, rect)


def draw_boss_bar(screen, boss):
    """Top-center boss HP bar (insanity threats), shown during boss waves:
    a dim track across the top with the hostile-red fill shrinking as the
    pool drains. The fraction is the boss's own hp/max_hp — one source of
    truth, the fight reads its own state."""
    fraction = max(boss.hp, 0) / boss.max_hp
    x = (SCREEN_WIDTH - BOSS_BAR_WIDTH) / 2
    track = pygame.Rect(x, BOSS_BAR_Y, BOSS_BAR_WIDTH, BOSS_BAR_HEIGHT)
    fill = pygame.Rect(x, BOSS_BAR_Y, BOSS_BAR_WIDTH * fraction, BOSS_BAR_HEIGHT)
    pygame.draw.rect(screen, BOSS_BAR_TRACK_COLOR, track, border_radius=4)
    pygame.draw.rect(screen, BOSS_BAR_FILL_COLOR, fill, border_radius=4)


_game_over_font_cache = None


def game_over_font():
    """Lazily built, larger font for the game-over banner."""
    global _game_over_font_cache
    if _game_over_font_cache is None:
        _game_over_font_cache = pygame.font.Font(None, GAME_OVER_FONT_SIZE)
    return _game_over_font_cache


def draw_game_over(screen, score, new_high=False, top_chain=0,
                   best_multiplier=1.0):
    """Centered game-over overlay (engagement F2): final score, the
    new-high-score state when the run set a record, the insanity run's top
    chain and best multiplier when it chained at all, and the R/Q prompt."""
    lines = [f"Game over — score {score}"]
    if new_high:
        lines.append("New high score!")
    if top_chain > 0:
        lines.append(
            f"Top chain {top_chain} — best multiplier x{best_multiplier:g}"
        )
    lines.append("press R to restart, Q to quit")

    font = game_over_font()
    height = len(lines) * GAME_OVER_LINE_STEP
    top = SCREEN_HEIGHT / 2 - height / 2
    for row, text in enumerate(lines):
        surface = font.render(text, True, HUD_COLOR)
        rect = surface.get_rect(
            center=(SCREEN_WIDTH / 2, top + (row + 0.5) * GAME_OVER_LINE_STEP)
        )
        screen.blit(surface, rect)


class WaveBanner:
    """Centered 'WAVE n' flash (engagement F3).

    The house dt-timer pattern — a float decremented every frame, visible
    while positive — with the text alpha fading out over the duration.
    """

    def __init__(self, duration=WAVE_BANNER_SECONDS):
        self.duration = duration
        self.timer = 0.0
        self.wave = 1

    def show(self, wave):
        """Arm the flash for a wave: 1 at game start/restart, n+1 on advance."""
        self.wave = wave
        self.timer = self.duration

    def update(self, dt):
        if self.timer > 0:
            self.timer = max(0.0, self.timer - dt)

    @property
    def visible(self):
        return self.timer > 0

    def draw(self, screen):
        if not self.visible:
            return
        surface = game_over_font().render(f"WAVE {self.wave}", True, HUD_COLOR)
        surface.set_alpha(int(255 * self.timer / self.duration))
        rect = surface.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3))
        screen.blit(surface, rect)
