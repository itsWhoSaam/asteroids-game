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
    HELP_FONT_SIZE,
    HELP_LINE_STEP,
    HELP_TITLE_STEP,
    HUD_FONT_SIZE,
    HUD_LINE_STEP,
    HUD_MARGIN,
    HUD_TAG_GAP,
    LOW_LIVES_PULSE_AMPLITUDE,
    LOW_LIVES_PULSE_SECONDS,
    LOW_LIVES_THRESHOLD,
    LOW_LIVES_VIGNETTE_ALPHA_STEP,
    LOW_LIVES_VIGNETTE_BANDS,
    LOW_LIVES_VIGNETTE_BAND_WIDTH,
    LOW_LIVES_VIGNETTE_COLOR,
    LOW_LIVES_VIGNETTE_MAX_ALPHA,
    PANEL_PAD_X,
    PANEL_PAD_Y,
    PALETTE,
    PAUSE_OVERLAY_DIM_ALPHA,
    PAUSE_OVERLAY_DIM_COLOR,
    POWERUPS,
    SCORE_LARGE,
    SCORE_MEDIUM,
    SCORE_SMALL,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    STATS_BLOCK_GAP,
    STATS_FONT_SIZE,
    STATS_LINE_STEP,
    VOLUME_DEFAULT,
    WAVE_BANNER_SECONDS,
    WAVE_BANNER_TILT_DEGREES,
)
from logger import log_event
import sound
from shop import UPGRADES

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


def low_lives_warning(lives, state):
    """The warning gate: exactly one life left on a live run (UX wave).

    Count-exact by design — at 2+ lives the line sits at rest, and the
    game-over screen owns its own overlay, so the warning never draws
    there even at the same count.
    """
    return state == "playing" and lives == LOW_LIVES_THRESHOLD


def pulse_scale(phase):
    """Size factor for the pulsing lives line: 1.0 at rest rising to
    LOW_LIVES_PULSE_AMPLITUDE at the half-period peak — one full breath
    per LOW_LIVES_PULSE_SECONDS. Pure, so the draw site just multiplies
    (the spawn-pop ease shape, sine instead of quadratic)."""
    breath = 0.5 - 0.5 * math.cos(2 * math.pi * phase / LOW_LIVES_PULSE_SECONDS)
    return 1.0 + (LOW_LIVES_PULSE_AMPLITUDE - 1.0) * breath


def vignette_band_rects(band, width=SCREEN_WIDTH, height=SCREEN_HEIGHT):
    """The four strip rects of one vignette band, 1-indexed from the edge.

    Bands step inward by LOW_LIVES_VIGNETTE_BAND_WIDTH and tile exactly —
    no region of the frame is double-darkened. Pure geometry, so the
    tests can pin disjointness, containment, and edge seating.
    """
    step = LOW_LIVES_VIGNETTE_BAND_WIDTH
    outer = (band - 1) * step
    inner = band * step
    return [
        pygame.Rect(outer, outer, width - 2 * outer, step),           # top
        pygame.Rect(outer, height - inner, width - 2 * outer, step),  # bottom
        pygame.Rect(outer, inner, step, height - 2 * inner),          # left
        pygame.Rect(width - inner, inner, step, height - 2 * inner),  # right
    ]


_vignette_strips_cache = None


def vignette_strips():
    """The vignette as pre-built uniform-alpha strips: [(surface, rect), ...]
    from the edge inward, strongest at the rim. Built once — per-pixel
    alpha would break the headless dummy drivers, so each band strip is a
    plain filled surface blitted with surface alpha (the pause-dim
    precedent), never a per-pixel-alpha surface."""
    global _vignette_strips_cache
    if _vignette_strips_cache is None:
        strips = []
        for band in range(1, LOW_LIVES_VIGNETTE_BANDS + 1):
            alpha = (
                LOW_LIVES_VIGNETTE_MAX_ALPHA
                - (band - 1) * LOW_LIVES_VIGNETTE_ALPHA_STEP
            )
            for rect in vignette_band_rects(band):
                surface = pygame.Surface(rect.size)
                surface.fill(LOW_LIVES_VIGNETTE_COLOR)
                surface.set_alpha(alpha)
                strips.append((surface, rect))
        _vignette_strips_cache = strips
    return _vignette_strips_cache


class LowLivesWarning:
    """Pulsing lives line + edge vignette while one life remains (UX wave).

    The house dt-timer pattern: the phase accumulates only while the gate
    is live, so the pulse freezes at rest the moment the run leaves it —
    respawn to more lives, game over, or a restart. Not persisted and not
    Game run state: every frame re-derives the gate from lives + state,
    so both restart hooks clear it for free.
    """

    def __init__(self):
        self.active = False
        self.phase = 0.0

    def update(self, dt, lives, state):
        """Re-evaluate the gate and age the pulse. Inactive frames reset
        the phase, so the next engagement breathes up from rest."""
        self.active = low_lives_warning(lives, state)
        if self.active:
            self.phase += dt
        else:
            self.phase = 0.0

    @property
    def pulse(self):
        """The lives line's size factor this frame, or None while at rest
        (draw_hud's quiet value)."""
        if not self.active:
            return None
        return pulse_scale(self.phase)

    def draw_vignette(self, screen):
        """The stepped edge vignette; drawn under the HUD text it must
        not dim."""
        if not self.active:
            return
        for surface, rect in vignette_strips():
            screen.blit(surface, rect.topleft)


def draw_hud(screen, score, lives=0, wave=0, muted=False, volume=None,
             lives_pulse=None, combo=None, dash_timer=None):
    """Draw the HUD top-left on a yellow halftone panel (visual V5). Score
    always shows; the lives and wave slots stay hidden while zero — F2 and
    F3 feed them.

    The audio tags render top-right as bare ink text — deliberately NOT on
    panels, so the MUTED tripwire's slot stays untouched unless a tag is
    actually showing: while playback is muted (F6) a MUTED tag sits in the
    corner, and a VOL N% tag (volume PR) sits beside it — to its left,
    separated by HUD_TAG_GAP — whenever a level is known.

    lives_pulse (low-lives warning): the lives line's pulse size factor
    (1.0–AMPLITUDE) while exactly one life remains, None at rest — that
    one line re-renders at the scaled size while the warning is live.

    Insanity slots (combo, dash), passed only while a run is live: the
    combo readout sits directly under the wave slot, amber and dimming as
    its window drains; the dash slot below shows ready or the cooling
    seconds.

    All text renders through the shared comicfx cache: one render per
    distinct (string, color, size), never per frame."""
    lines = [(f"Score: {score}", False)]
    if lives:
        lines.append((f"Lives: {lives}", lives_pulse is not None))
    if wave:
        lines.append((f"Wave: {wave}", False))

    # The insanity slots are extra panel rows under the basics (combo
    # under the wave slot). The combo's amber dims toward the window's
    # edge in the COLOR itself — the shared cache is keyed by (string,
    # color, size), so mutating a cached surface's alpha would bleed into
    # every other blit of the same string.
    # The insanity slots pin under the basics (combo under the wave slot,
    # dash below it): the combo slot empties when a chain breaks, but the
    # dash slot below must not slide up into its place — pinned rows, so a
    # dying chain never shifts the dash readout under the player's eye.
    combo_row = None
    if combo is not None and combo.active:
        remaining = max(combo.window, 0.0)
        combo_row = (
            f"COMBO x{combo.chain} ({remaining:.1f})",
            tuple(
                int(c * remaining / COMBO_WINDOW_SECONDS) for c in COMBO_COLOR
            ),
        )
    dash_row = None
    if dash_timer is not None:
        if dash_timer > 0:
            dash_row = (f"DASH {dash_timer:.1f}", DASH_COOLING_COLOR)
        else:
            dash_row = ("DASH READY", PALETTE["hud_ink"])

    # While a run is live (dash passed) the panel reserves both insanity
    # rows even when the combo slot is empty — no mid-play panel resizing.
    slot_count = 2 if dash_timer is not None else (1 if combo_row else 0)
    screen.blit(
        _hud_panel(len(lines) + slot_count),
        (HUD_MARGIN - PANEL_PAD_X, HUD_MARGIN - PANEL_PAD_Y),
    )
    for row, (text, pulsing) in enumerate(lines):
        if pulsing:
            # The pulse sweeps a small band of sizes per breath — the
            # (string, color, size) cache absorbs it like any other text.
            size = max(1, int(round(HUD_FONT_SIZE * lives_pulse)))
            surface = cached_text(text, PALETTE["hud_ink"], size)
        else:
            surface = cached_text(text, PALETTE["hud_ink"], HUD_FONT_SIZE)
        screen.blit(surface, (HUD_MARGIN, HUD_MARGIN + row * HUD_LINE_STEP))
    # Slot rows render at their pinned panel row indexes, same ink column.
    if combo_row is not None:
        text, color = combo_row
        surface = cached_text(text, color, HUD_FONT_SIZE)
        screen.blit(
            surface, (HUD_MARGIN, HUD_MARGIN + len(lines) * HUD_LINE_STEP)
        )
    if dash_row is not None:
        text, color = dash_row
        surface = cached_text(text, color, HUD_FONT_SIZE)
        screen.blit(
            surface,
            (HUD_MARGIN, HUD_MARGIN + (len(lines) + 1) * HUD_LINE_STEP),
        )
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


def game_over_font():
    """Larger font for the game-over banner and the wave banner — the
    shared bold comicfx font (visual V5)."""
    return shared_font(GAME_OVER_FONT_SIZE)


def draw_game_over(screen, score, new_high=False, top_chain=0,
                   best_multiplier=1.0):
    """Centered game-over overlay (engagement F2): final score, the
    new-high-score state when the run set a record, the insanity run's top
    chain and best multiplier when it chained at all, and the R/Q prompt —
    each line on its own yellow halftone caption panel (visual V5).

    Panel widths bucket to 32px so a run's score line reuses panels across
    restarts instead of growing the cache per point scored; text renders
    through the shared cache."""
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
        surface = cached_text(text, PALETTE["hud_ink"], GAME_OVER_FONT_SIZE)
        width = font.size(text)[0] + 2 * PANEL_PAD_X
        width = -(-width // 32) * 32  # ceil to the 32px bucket
        panel = panel_for(width, font.get_height() + 2 * PANEL_PAD_Y)
        center = (SCREEN_WIDTH / 2, top + (row + 0.5) * GAME_OVER_LINE_STEP)
        screen.blit(panel, panel.get_rect(center=center))
        screen.blit(surface, surface.get_rect(center=center))


def stats_font():
    """Dense font for the summary rows — the shared bold comicfx font at the
    help list's size, so the block reads as part of the V5 panel family."""
    return shared_font(STATS_FONT_SIZE)


def draw_run_summary(screen, stats):
    """The end-of-run stats block (run-stats PR): a title plus the four
    summary rows — shots/accuracy, rocks by tier, waves survived, credits
    earned idle-vs-click — each on its own yellow halftone caption panel,
    the game-over treatment at the denser size.

    Rows come pure from stats.summary_lines() (pinned by tests); widths
    bucket to 32px like the game-over panels; the block seats a fixed gap
    below the game-over overlay's worst case (three lines), above the shop
    panel's bottom edge. Only the game-over screen calls it — paused and
    live frames never see it."""
    lines = ["RUN SUMMARY"] + stats.summary_lines()
    font = stats_font()
    top = SCREEN_HEIGHT / 2 + 1.5 * GAME_OVER_LINE_STEP + STATS_BLOCK_GAP
    for row, text in enumerate(lines):
        surface = cached_text(text, PALETTE["hud_ink"], STATS_FONT_SIZE)
        width = -(-(font.size(text)[0] + 2 * PANEL_PAD_X) // 32) * 32
        panel = panel_for(width, font.get_height() + 2 * PANEL_PAD_Y)
        center = (
            SCREEN_WIDTH / 2,
            top + row * STATS_LINE_STEP + font.get_height() / 2,
        )
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


_pause_dim_cache = None


def pause_dim():
    """The one dark sheet blitted over the frame by every dimmed overlay —
    pause (Tier 1) and the help list (Tier 1) share the treatment.

    Uniform surface alpha via set_alpha — the WaveBanner fade precedent —
    never per-pixel alpha, which breaks headless dummy drivers. Cached
    once: rebuilding a full-screen surface every frame would be waste.
    """
    global _pause_dim_cache
    if _pause_dim_cache is None:
        dim = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        dim.fill(PAUSE_OVERLAY_DIM_COLOR)
        dim.set_alpha(PAUSE_OVERLAY_DIM_ALPHA)
        _pause_dim_cache = dim
    return _pause_dim_cache


def draw_pause(screen):
    """Centered PAUSED overlay over the dimmed frozen frame (Tier 1 pause):
    the key contract — resume (P) / restart (R) / quit (Q) — is the only
    UI a paused frame answers (mute and QUIT aside, in the event pump).

    Same caption-panel treatment as the game-over overlay (visual V5):
    one yellow halftone panel per line, ink-bordered, text through the
    shared cache — the pause prompt reads as part of the HUD family, not
    a raw white remnant. The dim sheet keeps uniform set_alpha: it is
    opaque color over the frame, no per-pixel alpha involved."""
    screen.blit(pause_dim(), (0, 0))
    lines = ["PAUSED", "press P to resume, R to restart, Q to quit"]
    font = game_over_font()
    height = len(lines) * GAME_OVER_LINE_STEP
    top = SCREEN_HEIGHT / 2 - height / 2
    for row, text in enumerate(lines):
        surface = cached_text(text, PALETTE["hud_ink"], GAME_OVER_FONT_SIZE)
        width = -(-(font.size(text)[0] + 2 * PANEL_PAD_X) // 32) * 32
        panel = panel_for(width, font.get_height() + 2 * PANEL_PAD_Y)
        center = (SCREEN_WIDTH / 2, top + (row + 0.5) * GAME_OVER_LINE_STEP)
        screen.blit(panel, panel.get_rect(center=center))
        screen.blit(surface, surface.get_rect(center=center))


def wave_banner_text(wave, milestone_credits=None):
    """The banner line for a wave: plain 'WAVE n', or the milestone
    announcement when the wave pays one (Tier 1 milestone rewards). Pure:
    the text resolves from the wave number and the grant alone."""
    if milestone_credits is None:
        return f"WAVE {wave}"
    return f"MILESTONE WAVE {wave} - SHIELD +{int(milestone_credits)} CR"


def help_font():
    """The dense-list font for the help overlay's keybind rows — the
    shared bold comicfx font (visual V5), so the rows measure the same
    glyphs the cache renders."""
    return shared_font(HELP_FONT_SIZE)


def help_keymap():
    """The help overlay's rows, as (group, keys, action) tuples.

    The shop and bought-powerup rows derive from the very tables the
    handlers read — shop.UPGRADES and constants.POWERUPS, the same
    table-driven shape the panel and the pump use — so a rebalance there
    re-renders here and the two can never disagree. The remaining rows are
    the hand-wired event-pump and polled keys, pinned to their live
    handlers by tests/test_help.py.
    """
    rows = [
        ("Ship", "W A S D", "thrust and rotate"),
        ("Ship", "Space", "shoot"),
        ("Ship", "Click", "chip the rock under the cursor"),
    ]
    for defn in UPGRADES:
        rows.append(("Shop", defn.key_label, f"{defn.title}: {defn.effect}"))
    for defn in POWERUPS.values():
        rows.append(
            ("Powerup", chr(defn["key"]), f"{defn['title']}: {defn['desc']}")
        )
    rows += [
        ("Audio", "M", "mute / unmute (persisted)"),
        ("Audio", "[ ]", "volume down / up"),
        ("Game", "P / Esc", "pause / resume"),
        ("Game", "H", "toggle this help"),
        ("Game over", "R / Q", "restart / quit"),
    ]
    return rows


def draw_help(screen):
    """Centered keybind list over dimmed play (Tier 1 help): H toggles it.

    The rows render from help_keymap() — the same table the tests pin to
    the live handlers — so the list is exactly what the game answers. The
    dim reuses the pause overlay's sheet: same treatment, one cache.
    """
    screen.blit(pause_dim(), (0, 0))
    rows = help_keymap()
    font = help_font()
    block_height = HELP_TITLE_STEP + len(rows) * HELP_LINE_STEP
    top = (SCREEN_HEIGHT - block_height) / 2
    title = cached_text("CONTROLS — press H to close", PALETTE["hud_ink"], GAME_OVER_FONT_SIZE)
    screen.blit(
        title, title.get_rect(center=(SCREEN_WIDTH / 2, top + HELP_TITLE_STEP / 2))
    )
    for row, (group, keys, action) in enumerate(rows):
        y = top + HELP_TITLE_STEP + row * HELP_LINE_STEP
        # Two columns around center: the key right-aligned, its action
        # left-aligned — a table that stays centered whatever the rows say.
        key_surface = cached_text(keys, PALETTE["hud_ink"], HELP_FONT_SIZE)
        screen.blit(
            key_surface,
            key_surface.get_rect(midright=(SCREEN_WIDTH / 2 - 24, y)),
        )
        action_surface = cached_text(
            f"{group}: {action}", PALETTE["hud_ink"], HELP_FONT_SIZE
        )
        screen.blit(
            action_surface,
            action_surface.get_rect(midleft=(SCREEN_WIDTH / 2 + 24, y)),
        )


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
        self._text = wave_banner_text(1)
        self._letters = None  # [(char, tilt, advance)] laid out per banner
        self._text_width = 0.0
        self._panel = None  # this banner's own plate; its alpha is mutated

    @property
    def text(self):
        """The armed banner line — 'WAVE n' or the milestone announcement."""
        return self._text

    def show(self, wave, milestone_credits=None):
        """Arm the flash for a wave: 1 at game start/restart, n+1 on advance.
        A milestone wave (Tier 1 rewards) announces its grant in the text."""
        self.wave = wave
        self.timer = self.duration
        self._text = wave_banner_text(wave, milestone_credits)
        self._letters = None  # the text changed: re-layout on next draw
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
                for index, char in enumerate(self._text)
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
