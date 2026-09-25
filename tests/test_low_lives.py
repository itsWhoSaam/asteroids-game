"""Tests for the low-lives warning (UX wave): exactly one life on a live
run pulses the HUD lives line and prints a stepped edge vignette — until
respawn, game over, or restart leaves the gate.

The pure gate, the pulse curve, and the band geometry get pinned math
tests; the draws get headless smoke checks with pixel assertions (surface
alpha only — per-pixel alpha would break the dummy drivers).
"""

import pygame
import pytest

from asteroid import Asteroid
from asteroidfield import AsteroidField
from comicfx import build_background_layers
from constants import (
    HUD_LINE_STEP,
    HUD_MARGIN,
    LOW_LIVES_PULSE_AMPLITUDE,
    LOW_LIVES_PULSE_SECONDS,
    LOW_LIVES_VIGNETTE_ALPHA_STEP,
    LOW_LIVES_VIGNETTE_BAND_WIDTH,
    LOW_LIVES_VIGNETTE_BANDS,
    LOW_LIVES_VIGNETTE_COLOR,
    LOW_LIVES_VIGNETTE_MAX_ALPHA,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from drones import DroneBay
from economy import Economy
from game import Game
from hud import (
    LowLivesWarning,
    WaveBanner,
    draw_hud,
    low_lives_warning,
    pulse_scale,
    vignette_band_rects,
    vignette_strips,
)
from main import render_world, update_world
from particles import Shake
from player import Player
from shot import Shot

PAPER = (23, 18, 58)  # PALETTE["paper"], inlined for plain-pixel comparisons


def make_game(tmp_path):
    """A real Game wired like main() — enough to drive hits and restarts."""
    pygame.init()
    updatable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    Player.containers = (updatable,)
    Asteroid.containers = (asteroids, updatable)
    Shot.containers = (shots, updatable)
    AsteroidField.containers = updatable
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, save_path=tmp_path / "game_save.json")
    return game


# --- The gate (threshold purity) ---------------------------------------------


@pytest.mark.parametrize("lives,expected", [(0, False), (1, True), (2, False), (3, False)])
def test_warning_active_exactly_at_one_life(lives, expected):
    """The gate is count-exact: live only at the threshold life."""
    assert low_lives_warning(lives, "playing") is expected


@pytest.mark.parametrize("state", ["game_over", "paused", ""])
def test_warning_never_active_outside_play(state):
    """The game-over screen owns its own overlay — the warning never draws
    there, whatever the life count (state is the second half of the gate)."""
    assert low_lives_warning(1, state) is False
    assert low_lives_warning(0, state) is False


def test_warning_tracks_a_real_run_to_game_over_and_restart(tmp_path):
    """End to end: three hits end a run and clear the warning; a restart's
    fresh lives keep it clear — no restart hook can leave it stuck on."""
    game = make_game(tmp_path)
    warning = LowLivesWarning()

    game.lives = 1
    warning.update(1 / 60, game.lives, game.state)
    assert warning.active is True

    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"
    warning.update(1 / 60, game.lives, game.state)
    assert warning.active is False
    assert warning.pulse is None

    game.restart()
    assert game.lives > 1
    warning.update(1 / 60, game.lives, game.state)
    assert warning.active is False


# --- The pulse curve ---------------------------------------------------------


def test_pulse_scale_breathes_from_rest_to_peak_and_back():
    """One cycle: rest at phase 0, peak at the half period, rest again."""
    assert pulse_scale(0.0) == pytest.approx(1.0)
    assert pulse_scale(LOW_LIVES_PULSE_SECONDS / 2) == pytest.approx(
        LOW_LIVES_PULSE_AMPLITUDE
    )
    assert pulse_scale(LOW_LIVES_PULSE_SECONDS) == pytest.approx(1.0)


def test_pulse_scale_stays_within_the_amplitude_band():
    """Every phase lands inside [1.0, AMPLITUDE] — the line can only grow
    toward the peak, never past it and never below its resting size."""
    for i in range(101):
        phase = LOW_LIVES_PULSE_SECONDS * i / 100
        assert 1.0 <= pulse_scale(phase) <= LOW_LIVES_PULSE_AMPLITUDE


def test_pulse_scale_rises_then_falls():
    """Monotone up on the first half of the breath, down on the second."""
    half = LOW_LIVES_PULSE_SECONDS / 2
    first = [pulse_scale(LOW_LIVES_PULSE_SECONDS * i / 100) for i in range(50)]
    second = [pulse_scale(half + LOW_LIVES_PULSE_SECONDS * i / 100) for i in range(50)]
    assert all(a <= b for a, b in zip(first, first[1:]))
    assert all(a >= b for a, b in zip(second, second[1:]))


def test_warning_phase_accumulates_only_while_active():
    """The dt-timer contract: active frames age the pulse, inactive frames
    reset it so the next engagement breathes up from rest."""
    warning = LowLivesWarning()
    warning.update(0.1, 1, "playing")
    warning.update(0.2, 1, "playing")
    assert warning.active is True
    assert warning.phase == pytest.approx(0.3)
    assert warning.pulse == pytest.approx(pulse_scale(0.3))

    warning.update(0.1, 3, "playing")
    assert warning.active is False
    assert warning.phase == 0.0
    assert warning.pulse is None


def test_warning_phase_holds_while_paused(tmp_path):
    """update_world freezes the warning with the rest of the sim: a paused
    frame ticks no phase, the resumed frame breathes again."""
    game = make_game(tmp_path)
    game.lives = 1
    field = AsteroidField(game)
    economy = Economy(save_path=tmp_path / "idle_save.json")
    drones = DroneBay(economy)
    banner = WaveBanner()
    shake = Shake()
    warning = LowLivesWarning()

    warning.update(0.1, game.lives, game.state)  # engage while live
    engaged_phase = warning.phase

    game.paused = True
    update_world(pygame.sprite.Group(), drones, pygame.sprite.Group(),
                 pygame.sprite.Group(), game.player, game, [], shake, field,
                 banner, economy, 1 / 60, warning)
    assert warning.phase == pytest.approx(engaged_phase)

    game.paused = False
    update_world(pygame.sprite.Group(), drones, pygame.sprite.Group(),
                 pygame.sprite.Group(), game.player, game, [], shake, field,
                 banner, economy, 1 / 60, warning)
    assert warning.phase > engaged_phase


# --- The vignette geometry ---------------------------------------------------


def test_vignette_bands_tile_the_edges_without_overlap():
    """All band strips are on-screen, positively sized, and pairwise
    disjoint — no region of the frame is double-darkened."""
    rects = [
        rect
        for band in range(1, LOW_LIVES_VIGNETTE_BANDS + 1)
        for rect in vignette_band_rects(band)
    ]
    assert len(rects) == 4 * LOW_LIVES_VIGNETTE_BANDS
    frame = pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
    for rect in rects:
        assert rect.width > 0 and rect.height > 0
        assert frame.contains(rect)
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert a.clip(b).size == (0, 0)


def test_vignette_leaves_the_center_free():
    """No band strip reaches the middle of the screen — the play field
    stays clear of the treatment."""
    center = (SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    for band in range(1, LOW_LIVES_VIGNETTE_BANDS + 1):
        for rect in vignette_band_rects(band):
            assert not rect.collidepoint(center)


def test_vignette_band_seats_hug_the_frame_edges():
    """Band 1's strips start at the very edges; each band's rim steps
    inward by exactly one band width."""
    first = vignette_band_rects(1)
    assert first[0].topleft == (0, 0)                       # top
    assert first[1].bottom == SCREEN_HEIGHT                 # bottom
    assert first[2].topleft == (0, LOW_LIVES_VIGNETTE_BAND_WIDTH)   # left
    assert first[3].topright == (SCREEN_WIDTH, LOW_LIVES_VIGNETTE_BAND_WIDTH)
    second = vignette_band_rects(2)
    assert second[0].topleft == (LOW_LIVES_VIGNETTE_BAND_WIDTH,) * 2


def test_vignette_strips_fade_inward():
    """The built strips carry uniform surface alpha, strongest at the rim
    and stepping down per band — and never per-pixel alpha."""
    pygame.init()
    strips = vignette_strips()
    assert len(strips) == 4 * LOW_LIVES_VIGNETTE_BANDS
    alphas = []
    for band in range(1, LOW_LIVES_VIGNETTE_BANDS + 1):
        band_strips = strips[(band - 1) * 4:band * 4]
        alpha = band_strips[0][0].get_alpha()
        alphas.append(alpha)
        expected = (
            LOW_LIVES_VIGNETTE_MAX_ALPHA
            - (band - 1) * LOW_LIVES_VIGNETTE_ALPHA_STEP
        )
        assert alpha == expected
        for surface, rect in band_strips:
            # Uniform surface alpha on a plain surface — the pause-dim
            # construction, which is what survives the dummy drivers.
            # (get_flags() reports SRCALPHA even for plain surfaces in
            # pygame 2.6, so it cannot distinguish per-pixel alpha here.)
            assert surface.get_alpha() == expected
    assert alphas == sorted(alphas, reverse=True)  # rim strongest


# --- Draw smoke --------------------------------------------------------------


def capture_lives_row(screen):
    """Pixels of the lives-line slot only (row 1), below the score line."""
    strip = pygame.Surface((300, 40))
    strip.blit(
        screen,
        (0, 0),
        pygame.Rect(HUD_MARGIN, HUD_MARGIN + HUD_LINE_STEP, 300, 40),
    )
    return strip


def ink_pixels(strip):
    """How many warm-white text-ink pixels the strip carries — the peak's
    larger glyphs must paint strictly more ink than the resting line.

    Counts PALETTE["hud_ink"] exactly, not non-background: the V5 comic
    panel plates the whole slot, so a !=background count saturates at the
    panel's coverage and cannot see the text at all (glyph cores render
    in pure ink; antialiased edges blend and do not count)."""
    return sum(
        1
        for x in range(strip.get_width())
        for y in range(strip.get_height())
        if strip.get_at((x, y))[:3] == (255, 247, 230)
    )


def test_draw_hud_pulsed_lives_smoke():
    """The pulsing lives line renders headless at rest and at peak, and the
    peak really paints a larger line (the pulse must be visible, not just
    legal)."""
    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()

    for pulse in (None, 1.0, LOW_LIVES_PULSE_AMPLITUDE):
        screen.fill((0, 0, 0))
        draw_hud(screen, 120, lives=1, wave=2, lives_pulse=pulse)  # smoke

    screen.fill((0, 0, 0))
    draw_hud(screen, 120, lives=1, wave=2, lives_pulse=None)
    rest_ink = ink_pixels(capture_lives_row(screen))
    screen.fill((0, 0, 0))
    draw_hud(screen, 120, lives=1, wave=2, lives_pulse=LOW_LIVES_PULSE_AMPLITUDE)
    peak_ink = ink_pixels(capture_lives_row(screen))
    assert peak_ink > rest_ink


def test_vignette_draw_smoke():
    """An active warning prints the vignette (the corner blends toward the
    danger red); an inactive one paints nothing."""
    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()

    warning = LowLivesWarning()
    screen.fill(PAPER)
    before = screen.get_at((2, 2))[:3]

    warning.update(0.01, 1, "playing")
    warning.draw_vignette(screen)  # smoke: must not raise under dummy drivers
    after = screen.get_at((2, 2))[:3]
    share = LOW_LIVES_VIGNETTE_MAX_ALPHA / 255
    expected = tuple(
        round(LOW_LIVES_VIGNETTE_COLOR[i] * share + before[i] * (1 - share))
        for i in range(3)
    )
    assert after != before  # the corner actually darkened
    assert all(abs(after[i] - expected[i]) <= 2 for i in range(3))

    fresh = LowLivesWarning()
    screen.fill(PAPER)
    untouched = screen.get_at((2, 2))[:3]
    fresh.draw_vignette(screen)
    assert screen.get_at((2, 2))[:3] == untouched  # inactive: nothing drew


def test_render_world_carries_the_warning(tmp_path):
    """The composition routes the warning: an active one vignettes the frame
    under the HUD, and the pulse reaches draw_hud through render_world."""
    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()
    game = make_game(tmp_path)
    game.lives = 1
    game.add_score(500)
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    background = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
    entities = pygame.sprite.Group()
    fx = pygame.sprite.Group()
    warning = LowLivesWarning()
    warning.update(0.01, game.lives, game.state)

    render_world(screen, world, background, entities, fx,
                 (0, 0), game, warning)  # smoke with the warning live
    corner = screen.get_at((2, 2))[:3]
    assert corner != PAPER  # the vignette printed over the paper
