"""Score tracking, persistent high score, and the HUD overlays (engagement F1).

F2's Game object absorbed the Score seam: it owns the run score and delegates
to Score for high-score persistence. main() renders whatever draw_hud and
draw_game_over draw.
"""

import json
import math
import sys

import pygame

from comicfx import (
    build_panel,
    cached_rotated_text,
    cached_text,
    shared_font,
)
from constants import (
    ASTEROID_MIN_RADIUS,
    BANNER_ALPHA_STEPS,
    GAME_OVER_FONT_SIZE,
    GAME_OVER_LINE_STEP,
    HUD_FONT_SIZE,
    HUD_LINE_STEP,
    HUD_MARGIN,
    HUD_TAG_GAP,
    PANEL_PAD_X,
    PANEL_PAD_Y,
    PALETTE,
    SCORE_LARGE,
    SCORE_MEDIUM,
    SCORE_SMALL,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    VOLUME_DEFAULT,
    WAVE_BANNER_SECONDS,
    WAVE_BANNER_TILT_DEGREES,
)
from logger import log_event

SAVE_PATH = "game_save.json"

# Missing or corrupt save data falls back to these, never a crash.
DEFAULT_SAVE = {"high_score": 0, "muted": False, "volume": VOLUME_DEFAULT}


def _valid_volume(volume):
    """Whole percent 0–100: the only thing the volume key accepts."""
    return (
        isinstance(volume, int)
        and not isinstance(volume, bool)
        and 0 <= volume <= 100
    )


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
    if not _valid_volume(save.get("volume")):
        save["volume"] = DEFAULT_SAVE["volume"]
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
        self.volume = self._data["volume"]
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
        self._data["volume"] = self.volume
        write_save(self.save_path, self._data)

    def set_muted(self, muted):
        """Persist the mute preference (F6) through the save loader: the
        whole save dict is written, so unknown keys still ride along."""
        self.muted = muted
        self._data["muted"] = muted
        write_save(self.save_path, self._data)
        return muted

    def set_volume(self, volume):
        """Persist the master volume level (UX wave) through the save
        loader, mirroring set_muted. The managed write updates the volume
        key; unknown keys still ride along."""
        self.volume = volume
        self._data["volume"] = self.volume
        write_save(self.save_path, self._data)
        return self.volume

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


_hud_font_cache = None


def hud_font():
    """Lazily built HUD font; pygame.font is ready once pygame.init() ran."""
    global _hud_font_cache
    if _hud_font_cache is None:
        _hud_font_cache = pygame.font.Font(None, HUD_FONT_SIZE)
    return _hud_font_cache


# Pre-rendered comic panels (visual V5), keyed by size: built once, blitted
# forever. Entries are shared and never mutated — a surface whose alpha is
# animated (the banner's own plate) builds private via build_panel instead.
_panel_cache = {}


def clear_panels():
    """Drop the panel cache (test isolation; no run-state depends on it)."""
    _panel_cache.clear()


def panel_for(width, height):
    """A pre-rendered comic panel of this size, shared per (width, height)."""
    key = (width, height)
    panel = _panel_cache.get(key)
    if panel is None:
        panel = build_panel(width, height)
        _panel_cache[key] = panel
    return panel


# Panel width for the HUD plate, measured once from the widest labels the
# slots can render — the plate is a fixed chunky comic shape, calm across
# frames. A score past ten digits would overflow it; unreachable in play.
_hud_panel_width = None


def _hud_panel(rows):
    global _hud_panel_width
    key = ("hud", rows)
    panel = _panel_cache.get(key)
    if panel is not None:
        return panel
    font = hud_font()
    if _hud_panel_width is None:
        _hud_panel_width = (
            max(
                font.size(label)[0]
                for label in ("Score: 999999999", "Lives: 99", "Wave: 999")
            )
            + 2 * PANEL_PAD_X
        )
    height = (rows - 1) * HUD_LINE_STEP + font.get_height() + 2 * PANEL_PAD_Y
    panel = build_panel(_hud_panel_width, height)
    _panel_cache[key] = panel
    return panel


def draw_hud(screen, score, lives=0, wave=0, muted=False, volume=None):
    """Draw the HUD top-left on a yellow halftone panel (visual V5). Score
    always shows; the lives and wave slots stay hidden while zero — F2 and
    F3 feed them.

    The audio tags render top-right as bare ink text — deliberately NOT on
    panels, so the MUTED tripwire's slot stays untouched unless a tag is
    actually showing: while playback is muted (F6) a MUTED tag sits in the
    corner, and a VOL N% tag (volume PR) sits beside it — to its left,
    separated by HUD_TAG_GAP — whenever a level is known.

    All text renders through the shared comicfx cache: one render per
    distinct (string, color, size), never per frame."""
    lines = [f"Score: {score}"]
    if lives:
        lines.append(f"Lives: {lives}")
    if wave:
        lines.append(f"Wave: {wave}")

    screen.blit(
        _hud_panel(len(lines)),
        (HUD_MARGIN - PANEL_PAD_X, HUD_MARGIN - PANEL_PAD_Y),
    )
    for row, text in enumerate(lines):
        surface = cached_text(text, PALETTE["hud_ink"], HUD_FONT_SIZE)
        screen.blit(surface, (HUD_MARGIN, HUD_MARGIN + row * HUD_LINE_STEP))

    muted_rect = None
    if muted:
        surface = cached_text("MUTED", PALETTE["hud_ink"], HUD_FONT_SIZE)
        muted_rect = surface.get_rect(
            topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
        )
        screen.blit(surface, muted_rect)
    if volume is not None:
        surface = cached_text(f"VOL {volume}%", PALETTE["hud_ink"], HUD_FONT_SIZE)
        right = SCREEN_WIDTH - HUD_MARGIN
        if muted_rect is not None:
            right -= muted_rect.width + HUD_TAG_GAP
        screen.blit(surface, surface.get_rect(topright=(right, HUD_MARGIN)))


def game_over_font():
    """Larger font for the game-over banner and the wave banner — the
    shared bold comicfx font (visual V5)."""
    return shared_font(GAME_OVER_FONT_SIZE)


def draw_game_over(screen, score, new_high=False):
    """Centered game-over overlay (engagement F2): final score, the
    new-high-score state when the run set a record, and the R/Q prompt —
    each line on its own yellow halftone caption panel (visual V5).

    Panel widths bucket to 32px so a run's score line reuses panels across
    restarts instead of growing the cache per point scored; text renders
    through the shared cache."""
    lines = [f"Game over — score {score}"]
    if new_high:
        lines.append("New high score!")
    lines.append("press R to restart, Q to quit")

    font = game_over_font()
    height = len(lines) * GAME_OVER_LINE_STEP
    top = SCREEN_HEIGHT / 2 - height / 2
    for row, text in enumerate(lines):
        surface = cached_text(text, PALETTE["hud_ink"], GAME_OVER_FONT_SIZE)
        width = font.size(text)[0] + 2 * PANEL_PAD_X
        width = -(-width // 32) * 32  # ceil to the 32px bucket
        panel = panel_for(width, font.get_height() + 2 * PANEL_PAD_Y)
        center = (SCREEN_WIDTH / 2, top + (row + 0.5) * GAME_OVER_LINE_STEP)
        screen.blit(panel, panel.get_rect(center=center))
        screen.blit(surface, surface.get_rect(center=center))


def banner_alpha(timer, duration):
    """Pure fade curve for the wave banner: this frame's alpha, quantized
    to BANNER_ALPHA_STEPS bands — the bands are the shared render cache's
    color keys, so a whole fade costs STEPS cached letter surfaces, never
    one per frame. Full brightness while freshly shown, zero at the end."""
    if timer <= 0 or duration <= 0:
        return 0
    fraction = min(1.0, timer / duration)
    band = math.ceil(fraction * BANNER_ALPHA_STEPS)  # 1..STEPS
    return round(255 * band / BANNER_ALPHA_STEPS)


def letter_tilt(index):
    """Pure per-letter tilt (degrees) for the wave banner: alternating
    sign down the line — slight, deterministic hand-lettering, and the
    rotated cache's keys recur across waves instead of accumulating."""
    tilt = WAVE_BANNER_TILT_DEGREES
    return tilt if index % 2 == 0 else -tilt


class WaveBanner:
    """Centered 'WAVE n' flash (engagement F3).

    The house dt-timer pattern — a float decremented every frame, visible
    while positive. V5 lettering: each character renders as its own cached
    surface, tilted by letter_tilt, with the fade baked into the glyph
    colors as this frame's alpha parameter (banner_alpha) — surface
    set_alpha does not compose with per-pixel SRCALPHA, so the text never
    touches it. The panel behind the letters is the one place surface
    alpha still fades: it is opaque (no per-pixel alpha to conflict with),
    the halftone print's measured mechanism, on the banner's own plate —
    shared panel entries are borrowed, never mutated.

    Surfaces resolve lazily per wave at the first draw (show() must stay
    pygame-free: it runs in tests that never initialize pygame).
    """

    def __init__(self, duration=WAVE_BANNER_SECONDS):
        self.duration = duration
        self.timer = 0.0
        self.wave = 1
        self._letters = None  # [(char, tilt, advance)] laid out per wave
        self._text_width = 0.0
        self._panel = None  # this banner's own plate; its alpha is mutated

    def show(self, wave):
        """Arm the flash for a wave: 1 at game start/restart, n+1 on advance."""
        self.wave = wave
        self.timer = self.duration
        self._letters = None  # the wave number changed: re-layout on next draw
        self._panel = None

    def update(self, dt):
        if self.timer > 0:
            self.timer = max(0.0, self.timer - dt)

    @property
    def visible(self):
        return self.timer > 0

    def draw(self, screen):
        if not self.visible:
            return
        if self._letters is None:
            font = game_over_font()
            self._letters = [
                (char, letter_tilt(index), font.size(char)[0])
                for index, char in enumerate(f"WAVE {self.wave}")
            ]
            self._text_width = sum(advance for _, _, advance in self._letters)
            self._panel = build_panel(
                self._text_width + 2 * PANEL_PAD_X,
                font.get_height() + 2 * PANEL_PAD_Y,
            )

        alpha = banner_alpha(self.timer, self.duration)
        center = (SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3)
        self._panel.set_alpha(alpha)  # opaque plate: surface alpha is safe
        screen.blit(self._panel, self._panel.get_rect(center=center))

        color = (*PALETTE["hud_ink"], alpha)  # the fade lives in the glyphs
        x = SCREEN_WIDTH / 2 - self._text_width / 2
        for char, tilt, advance in self._letters:
            if char != " ":
                surface = cached_rotated_text(
                    char, color, GAME_OVER_FONT_SIZE, tilt
                )
                screen.blit(
                    surface, surface.get_rect(center=(x + advance / 2, center[1]))
                )
            x += advance
