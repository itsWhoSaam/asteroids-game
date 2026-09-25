"""Visual V5 contract tests: the comic HUD family.

- banner_alpha: the per-frame fade parameter that replaces surface
  set_alpha — quantized to BANNER_ALPHA_STEPS bands, monotonic, 255 fresh,
  0 outside the window (per-pixel SRCALPHA and set_alpha do not compose).
- letter_tilt: the alternating hand-lettering tilt.
- build_panel / panel_for: opaque yellow halftone plates with an ink
  border, built once and shared — never per-pixel alpha, never mutated.
- WaveBanner.draw: glyphs fade through the baked alpha parameter, the
  banner's own plate is private (shared panel entries are never mutated),
  and a whole fade costs BANNER_ALPHA_STEPS letter renders — not one per
  frame (the allocation pattern the survey flagged, dead for good).
- Overlays: the game-over and pause prompts sit on the same caption
  panels with text through the shared cache; the HUD plate covers the
  score slots while the MUTED corner stays bare (test_sound pins those
  pixels; this pins the layout choice).
"""

import pygame
import pytest

import comicfx
from comicfx import build_panel, cached_rotated_text, cached_text
from constants import (
    BANNER_ALPHA_STEPS,
    GAME_OVER_FONT_SIZE,
    GAME_OVER_LINE_STEP,
    HUD_MARGIN,
    PANEL_PAD_X,
    PANEL_PAD_Y,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    WAVE_BANNER_TILT_DEGREES,
)
from hud import (
    WaveBanner,
    banner_alpha,
    clear_panels,
    draw_game_over,
    draw_hud,
    draw_pause,
    game_over_font,
    letter_tilt,
    panel_for,
)

PAPER = PALETTE["paper"]
INK = PALETTE["hud_ink"]
PANEL_YELLOW = PALETTE["hud_panel"]


class CountingFont:
    """Delegates render() to a real font while tallying calls (pygame.font
    is an immutable C type, so the factory seam is what gets patched)."""

    def __init__(self, font, calls):
        self._font = font
        self._calls = calls

    def render(self, text, antialias, color=None, background=None):
        self._calls.append(text)
        return self._font.render(text, antialias, color, background)

    def size(self, text):
        return self._font.size(text)

    def get_height(self):
        return self._font.get_height()


@pytest.fixture
def screen():
    pygame.init()
    surface = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    surface.fill(PAPER)
    clear_panels()
    comicfx._text_fonts.clear()
    comicfx._text_cache.clear()
    comicfx._rotated_cache.clear()
    yield surface
    clear_panels()


# --- the fade curve ---------------------------------------------------------


def test_banner_alpha_curve():
    """banner_alpha is the per-frame fade parameter: 255 while the banner
    is fresh, quantized bands on the way down, exactly 0 at and past the
    end — the values a color key needs to stay cacheable."""
    assert banner_alpha(0.0, 2.0) == 0  # expired: invisible
    assert banner_alpha(-0.5, 2.0) == 0  # past the end
    assert banner_alpha(1.5, 0.0) == 0  # degenerate duration guard
    assert banner_alpha(2.0, 2.0) == 255  # freshly shown: full ink
    assert banner_alpha(1.0, 2.0) == 128  # the halfway band

    sweep = [banner_alpha(t, 2.0) for t in [2.0 * k / 24 for k in range(25)]]
    assert all(later >= earlier for earlier, later in zip(sweep, sweep[1:]))
    assert len(set(sweep)) <= BANNER_ALPHA_STEPS + 1  # quantized, not continuous


def test_banner_tilt_alternates():
    """letter_tilt hands lettering its slight comic wobble: alternating
    sign down the line at the locked magnitude."""
    tilts = [letter_tilt(i) for i in range(6)]
    assert tilts == [WAVE_BANNER_TILT_DEGREES, -WAVE_BANNER_TILT_DEGREES] * 3


# --- the panel plates -------------------------------------------------------


def test_panel_is_opaque_ink_edged_halftone():
    """build_panel: a fixed-size opaque plate — no per-pixel alpha (the
    uniform set_alpha fade depends on it) — yellow with a black ink
    border and the darker halftone dot grid showing through."""
    panel = build_panel(120, 60)
    assert panel.get_size() == (120, 60)
    assert not panel.get_flags() & pygame.SRCALPHA
    assert panel.get_at((60, 1))[:3] == (0, 0, 0)  # top ink edge (3px band)
    assert panel.get_at((60, 58))[:3] == (0, 0, 0)  # bottom ink edge
    assert panel.get_at((1, 30))[:3] == (0, 0, 0)  # left ink edge
    assert panel.get_at((60, 30))[:3] == PANEL_YELLOW  # plate interior
    dots = [
        (x, y)
        for x in range(8, 112)
        for y in range(8, 52)
        if panel.get_at((x, y))[:3] == PALETTE["hud_panel_dot"]
    ]
    assert dots  # the halftone print is really in the plate


def test_panel_cache_shares_and_clears():
    """panel_for hands out one shared surface per size — built once,
    blitted forever — and clear_panels drops them (test isolation)."""
    first = panel_for(80, 40)
    assert panel_for(80, 40) is first
    assert panel_for(80, 41) is not first  # a different size builds its own
    clear_panels()
    assert panel_for(80, 40) is not first  # cleared: rebuilt from scratch


def test_hud_panel_sits_behind_score_and_slots(screen):
    """The HUD plate is a yellow panel behind the score slots — ink and
    glyphs ride on it — while the top-right corner stays bare paper for
    the MUTED tripwire whenever nothing is showing there."""
    draw_hud(screen, 12345, lives=2, wave=3)

    # inside the plate's left padding: pure panel, where the old flat HUD
    # left paper (either the plate or one of its halftone dots)
    assert screen.get_at((12, 40))[:3] in (PANEL_YELLOW, PALETTE["hud_panel_dot"])
    assert screen.get_at((SCREEN_WIDTH - 2, 2))[:3] == PAPER  # the tripwire slot


def _caption_padding_point(screen, text, center_y):
    """A pixel inside the caption panel's left padding, clear of the text."""
    width = game_over_font().size(text)[0]
    return (round(SCREEN_WIDTH / 2 - width / 2) - 6, round(center_y))


def test_game_over_lines_sit_on_caption_panels(screen):
    """Every game-over line gets its own yellow caption panel — the text
    renders through the shared cache, so a second identical draw adds no
    new text surfaces."""
    draw_game_over(screen, 1250, new_high=True)

    cache_size = len(comicfx._text_cache)
    draw_game_over(screen, 1250, new_high=True)
    assert len(comicfx._text_cache) == cache_size  # cache reused, not refilled

    lines = ["Game over — score 1250", "New high score!", "press R to restart, Q to quit"]
    height = len(lines) * GAME_OVER_LINE_STEP
    top = SCREEN_HEIGHT / 2 - height / 2
    for row, text in enumerate(lines):
        point = _caption_padding_point(screen, text, top + (row + 0.5) * GAME_OVER_LINE_STEP)
        # panel shows here: the plate or one of its halftone dots
        assert screen.get_at(point)[:3] in (PANEL_YELLOW, PALETTE["hud_panel_dot"]), text


def test_pause_prompt_sits_on_caption_panels(screen):
    """The pause prompt (merged Tier 1 overlay) rides the same caption
    panels over the dim sheet — part of the HUD family, not a raw white
    remnant."""
    draw_pause(screen)

    assert screen.get_at((20, 700))[:3] != PAPER  # the dim sheet is down
    point = _caption_padding_point(
        screen, "PAUSED", SCREEN_HEIGHT / 2 - GAME_OVER_LINE_STEP / 2
    )
    assert screen.get_at(point)[:3] in (PANEL_YELLOW, PALETTE["hud_panel_dot"])

    cache_size = len(comicfx._text_cache)
    draw_pause(screen)
    assert len(comicfx._text_cache) == cache_size


# --- the banner's fade ------------------------------------------------------


def test_banner_draws_fading_panel_and_glyphs(screen):
    """The fade is a per-frame alpha parameter baked into glyph colors:
    the same banner at full and near-spent timers draws the same tilted
    letters, dimmer — every differing pixel strictly darker, the panel
    fading with it. No surface set_alpha on the letters anywhere."""
    banner = WaveBanner(duration=2.0)
    banner.show(1)
    banner.draw(screen)
    panel_rect = banner._panel.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 3))
    plate_point = (panel_rect.left + 7, panel_rect.centery)  # ink-free plate strip
    panel_full = screen.get_at(plate_point)
    full = [
        screen.get_at((x, y))
        for y in range(200, 280, 4)
        for x in range(500, 780, 4)
    ]

    banner.show(1)
    banner.timer = 0.2  # near-spent: the lowest band
    screen.fill(PAPER)  # the game composites each frame fresh — the plate
    banner.draw(screen)  # must fade over paper, not over its previous self
    panel_dim = screen.get_at(plate_point)
    dim = [
        screen.get_at((x, y))
        for y in range(200, 280, 4)
        for x in range(500, 780, 4)
    ]

    differing = [(a, b) for a, b in zip(full, dim) if a != b]
    assert len(differing) >= 20  # the tilted glyphs live here
    # every differing pixel moves toward the paper backdrop: colored ink
    # dims, black ink brightens — coverage fades, never the shape
    def _from_paper(p):
        return (p.r - PAPER[0]) ** 2 + (p.g - PAPER[1]) ** 2 + (p.b - PAPER[2]) ** 2

    assert all(_from_paper(a) > _from_paper(b) for a, b in differing)
    # the plate fades with the same parameter: yellow family down to a
    # paper-blended dim — the banner's one surface-level set_alpha
    assert panel_full[:3] in (PANEL_YELLOW, PALETTE["hud_panel_dot"])
    assert sum(panel_dim[:3]) < sum(panel_full[:3]) - 40


def test_banner_panel_is_private_not_shared(screen):
    """The banner mutates its own plate's alpha every frame, so it must
    never borrow a shared panel_for entry — those are never mutated."""
    import hud  # noqa: PLC0415 — the panel registry itself is the subject

    banner = WaveBanner(duration=2.0)
    banner.show(1)
    shared_ids_before = {id(entry) for entry in hud._panel_cache.values()}
    banner.draw(screen)

    assert banner._panel is not None
    assert id(banner._panel) not in shared_ids_before  # own plate, not shared


def test_banner_fade_costs_bounded_letter_renders(screen, monkeypatch):
    """A whole two-second fade renders each banner letter at most
    BANNER_ALPHA_STEPS times — once per alpha band — never once per
    frame. This is the quantization paying off in the hot path."""
    calls = []
    fonts = {}

    def counting_font(size):
        real = fonts.setdefault(size, pygame.font.Font(None, size))
        return CountingFont(real, calls)

    monkeypatch.setattr(comicfx, "_font", counting_font)

    banner = WaveBanner(duration=2.0)
    banner.show(2)
    for _ in range(130):  # full fade plus tail — 120 visible frames
        banner.draw(screen)
        banner.update(1 / 60)

    w_renders = calls.count("W")
    assert 1 <= w_renders <= BANNER_ALPHA_STEPS  # one base render, bands are fills
    assert len(calls) < 120  # the whole fade: far under one render per frame


def test_banner_rerender_after_show_reuses_letter_cache(screen, monkeypatch):
    """A restart re-arms the banner for the same wave: the letters lay out
    again, but every glyph is a shared-cache hit — zero new renders."""
    calls = []
    fonts = {}

    def counting_font(size):
        real = fonts.setdefault(size, pygame.font.Font(None, size))
        return CountingFont(real, calls)

    monkeypatch.setattr(comicfx, "_font", counting_font)

    banner = WaveBanner(duration=2.0)
    banner.show(2)
    banner.draw(screen)
    renders_after_first = len(calls)
    assert renders_after_first > 0

    banner.show(2)  # restart: same wave, same bands
    banner.draw(screen)
    assert len(calls) == renders_after_first  # letters came from the cache


def test_cached_text_identity():
    """The shared cache hands out the same surface for the same key —
    the property every overlay draw leans on."""
    first = cached_text("Score: 1", INK, 28)
    assert cached_text("Score: 1", INK, 28) is first
    rotated = cached_rotated_text("W", INK, GAME_OVER_FONT_SIZE, 4)
    assert cached_rotated_text("W", INK, GAME_OVER_FONT_SIZE, 4) is rotated
