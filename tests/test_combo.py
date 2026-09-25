"""Insanity core: the combo multiplier — chains, expiry, milestones, and the
score-only seam (Game.register_kill).

Locked decision under test: combo is a score feature, never a currency
feature. register_kill pays points × combo_multiplier through the F1 score
seam; credits mint through the destruction diff exactly as they did before,
unmultiplied — no test here (or anywhere) may grow the ledger.
"""

import json

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    COMBO_CAP,
    COMBO_MILESTONES,
    COMBO_WINDOW_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from hud import ComboMeter, combo_multiplier, draw_game_over, draw_hud, points_for
from main import handle_collisions
from player import Player
from powerups import PowerUpType
from shot import Shot


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def make_world(tmp_path):
    """A Game wired to a real player and groups, saving into tmp_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    player = Player(100, 660)  # far from the rocks: no player hit
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, powerups


# --- combo_multiplier (pure seam) ---------------------------------------------


@pytest.mark.parametrize(
    "chain, expected",
    [
        (0, 1.0),
        (1, 1.0),    # the first kill pays face value
        (2, 1.25),   # one step
        (5, 2.0),    # the milestone tier
        (9, 3.0),
        (13, 4.0),
        (16, 4.75),  # one step below the ceiling
        (17, COMBO_CAP),
    ],
)
def test_combo_multiplier_table(chain, expected):
    assert combo_multiplier(chain) == pytest.approx(expected)


def test_combo_multiplier_steps_linearly_to_the_cap():
    for chain in range(2, 17):
        assert combo_multiplier(chain) == pytest.approx(1.0 + 0.25 * (chain - 1))
    assert combo_multiplier(17) == COMBO_CAP
    assert combo_multiplier(100) == COMBO_CAP  # capped forever past the ceiling


def test_combo_multiplier_is_pure_in_step_and_cap():
    assert combo_multiplier(3, step=0.5) == 2.0
    assert combo_multiplier(5, step=0.5, cap=1.5) == 1.5  # capped
    assert combo_multiplier(9, step=0.0) == 1.0  # a zero step pays no bonus


# --- ComboMeter ---------------------------------------------------------------


def test_register_kill_builds_the_chain_and_tracks_run_stats():
    meter = ComboMeter()
    for expected_chain in range(1, 8):
        chain = meter.register_kill()
        assert chain == expected_chain
        assert meter.window == pytest.approx(COMBO_WINDOW_SECONDS)

    assert meter.chain == 7
    assert meter.top == 7  # best chain this run
    assert meter.best_multiplier == pytest.approx(combo_multiplier(7))
    assert meter.active


def test_milestones_log_once_per_run_and_rearm_on_reset(tmp_path):
    assert all(m in COMBO_MILESTONES for m in (5, 10))

    meter = ComboMeter()
    for _ in range(5):
        meter.register_kill()
    assert sum(e["type"] == "combo_milestone" for e in read_events(tmp_path)) == 1

    meter.register_kill()  # climbing past the tier must not re-log it
    assert sum(e["type"] == "combo_milestone" for e in read_events(tmp_path)) == 1

    meter.break_chain()
    for _ in range(5):
        meter.register_kill()  # a re-climbed tier stays silent: once per run
    assert sum(e["type"] == "combo_milestone" for e in read_events(tmp_path)) == 1

    meter.reset()  # a fresh run re-arms every milestone
    for _ in range(5):
        meter.register_kill()
    assert sum(e["type"] == "combo_milestone" for e in read_events(tmp_path)) == 2


def test_tick_expires_the_window_and_breaks(tmp_path):
    meter = ComboMeter()
    for _ in range(4):
        meter.register_kill()

    meter.tick(COMBO_WINDOW_SECONDS / 2)  # half-drained: still live
    assert meter.chain == 4
    meter.tick(COMBO_WINDOW_SECONDS)  # fully drained: expired
    assert meter.chain == 0
    assert meter.window == 0.0
    assert not meter.active
    # The break was worth logging (4 >= COMBO_BREAK_MIN_CHAIN).
    breaks = [e for e in read_events(tmp_path) if e["type"] == "combo_break"]
    assert len(breaks) == 1 and breaks[0]["chain"] == 4


def test_breaking_a_short_chain_is_silent_and_unlogged(tmp_path):
    meter = ComboMeter()
    meter.register_kill()
    meter.register_kill()  # 2 < COMBO_BREAK_MIN_CHAIN
    meter.break_chain()
    assert meter.chain == 0
    assert sum(e["type"] == "combo_break" for e in read_events(tmp_path)) == 0


def test_run_stats_survive_a_break_but_die_with_a_reset():
    meter = ComboMeter()
    for _ in range(6):
        meter.register_kill()
    meter.break_chain()
    assert meter.chain == 0
    assert meter.top == 6  # the game-over stat survives the break
    assert meter.best_multiplier == pytest.approx(combo_multiplier(6))

    meter.reset()
    assert meter.top == 0
    assert meter.best_multiplier == 1.0


# --- Game wiring --------------------------------------------------------------


def test_register_kill_pays_points_times_multiplier(tmp_path):
    pygame.init()
    game, *_ = make_world(tmp_path)
    small = points_for(ASTEROID_MIN_RADIUS)  # 100

    game.register_kill(small)  # chain 1: face value
    assert game.score == small

    game.register_kill(small)  # chain 2: x1.25
    assert game.score == small + round(small * combo_multiplier(2))


def test_register_kill_drives_the_meter(tmp_path):
    pygame.init()
    game, *_ = make_world(tmp_path)

    for _ in range(5):
        game.register_kill(points_for(ASTEROID_MIN_RADIUS))

    assert game.combo.chain == 5
    assert game.combo.top == 5


def test_life_loss_breaks_the_chain_but_keeps_the_run_stats(tmp_path):
    pygame.init()
    game, player, *_ = make_world(tmp_path)
    for _ in range(4):
        game.register_kill(points_for(ASTEROID_MIN_RADIUS))
    assert game.combo.chain == 4

    game.player_hit()  # a real life lost

    assert game.combo.chain == 0
    assert game.combo.top == 4  # the game-over stat survives
    assert game.combo.best_multiplier == pytest.approx(combo_multiplier(4))


def test_shielded_hit_keeps_the_chain(tmp_path):
    pygame.init()
    game, player, *_ = make_world(tmp_path)
    player.activate_powerup(PowerUpType.SHIELD)
    for _ in range(3):
        game.register_kill(points_for(ASTEROID_MIN_RADIUS))

    game.player_hit()  # absorbed by the shield

    assert game.lives == 3  # no life lost
    assert game.combo.chain == 3  # the chain survives the absorbed hit


def test_game_over_logs_with_the_run_and_restart_zeroes_everything(tmp_path):
    pygame.init()
    game, player, *_ = make_world(tmp_path)
    for _ in range(4):
        game.register_kill(points_for(ASTEROID_MIN_RADIUS))
    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"
    # The overlay reads the stats right now — they must not be zeroed yet.
    assert game.combo.top == 4

    game.restart()

    assert game.combo.chain == 0
    assert game.combo.top == 0
    assert game.combo.best_multiplier == 1.0
    assert game.combo.window == 0.0


# --- sweep wiring & HUD -------------------------------------------------------


def test_sweep_shot_kill_counts_as_chain_kill(tmp_path):
    """The sweep's shot branch routes through register_kill: the meter
    advances and a second kill inside the window pays the stepped rate."""
    pygame.init()
    game, player, asteroids, shots, powerups = make_world(tmp_path)

    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 3)  # large rock: 20 points
    Shot(640, 360)
    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.combo.chain == 1
    first = game.score
    assert first == points_for(ASTEROID_MIN_RADIUS * 3)  # chain 1: face value

    # Far from the first wreck — the first rock's split children still drift
    # at its death site, and this shot must hit exactly the new rock.
    Asteroid(200, 200, ASTEROID_MIN_RADIUS * 3)  # another large rock
    Shot(200, 200)
    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.combo.chain == 2
    assert game.score == first + round(first * combo_multiplier(2))


def test_hud_draws_the_combo_readout_while_a_chain_lives():
    """The amber readout renders under the wave slot while a chain lives and
    leaves those pixels empty once the chain is gone."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    meter = ComboMeter()
    for _ in range(3):
        meter.register_kill()

    def slot_pixels(target=None):
        # The combo row sits directly under the wave slot (row 3 while
        # lives and wave are shown).
        surface = target if target is not None else screen
        y0 = 12 + 3 * 34
        return [
            surface.get_at((x, y))
            for x in range(12, 250, 4)
            for y in range(y0, y0 + 28, 3)
        ]

    screen.fill("black")
    draw_hud(screen, 0, lives=3, wave=2, combo=meter, dash_timer=0.0)
    assert any(pixel != (0, 0, 0, 255) for pixel in slot_pixels())

    meter.break_chain()  # chain gone: the readout goes with it
    screen.fill("black")
    draw_hud(screen, 0, lives=3, wave=2, combo=meter, dash_timer=0.0)
    # The panel plate sits behind the slot rows (visual V5), so "gone"
    # means the band renders exactly what the chainless HUD renders — no
    # lingering combo text, plate included.
    chainless = pygame.Surface(screen.get_size())
    chainless.fill("black")
    draw_hud(chainless, 0, lives=3, wave=2, dash_timer=0.0)
    assert slot_pixels() == slot_pixels(chainless)


def test_game_over_overlay_reports_the_run_stats_headless():
    """The overlay gains the top-chain/best-multiplier line without losing
    its defaults (a chainless run reports nothing extra)."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    screen.fill("black")
    draw_game_over(screen, 500, new_high=False, top_chain=7,
                   best_multiplier=2.5)  # must not crash
    screen.fill("black")
    draw_game_over(screen, 500, new_high=True, top_chain=0,
                   best_multiplier=1.0)  # chainless run: no stat line
