"""Tests for score, persistent high score, and the HUD (engagement F1)."""

import json

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    HUD_FONT_SIZE,
    HUD_MARGIN,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from hud import (
    DEFAULT_SAVE,
    Score,
    draw_game_over,
    draw_hud,
    hud_font,
    load_save,
    points_for,
    write_save,
)
from game import Game
from main import handle_collisions
from player import Player
from powerups import PowerUp
from shot import Shot


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize(
    "radius, expected",
    [
        (ASTEROID_MIN_RADIUS, 100),      # small: 1x the minimum radius
        (ASTEROID_MIN_RADIUS * 2, 50),   # medium: 2x
        (ASTEROID_MIN_RADIUS * 3, 20),   # large: the field's biggest spawn (3x)
        (ASTEROID_MIN_RADIUS * 4, 20),   # large: the spec's 4x anchor
        (ASTEROID_MIN_RADIUS - 1, 100),  # below 1x still scores the small tier
    ],
)
def test_points_for_size_table(radius, expected):
    assert points_for(radius) == expected


def test_save_roundtrip(tmp_path):
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 1234, "muted": True, "volume": 70})
    assert load_save(path) == {"high_score": 1234, "muted": True, "volume": 70}


def test_write_preserves_unknown_keys_for_other_features(tmp_path):
    """Read-modify-write: keys owned by later features (idle economy) must
    survive Score's persistence."""
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 500, "muted": False, "currency": 42, "upgrades": ["boom"]})

    score = Score(path)
    score.add_score(600)  # beats the stored high score, triggering a write

    on_disk = json.loads(path.read_text())
    assert on_disk["high_score"] == 600
    assert on_disk["currency"] == 42
    assert on_disk["upgrades"] == ["boom"]


def test_corrupt_managed_field_preserves_unknown_keys(tmp_path):
    path = tmp_path / "game_save.json"
    path.write_text('{"high_score": "lots", "currency": 7}')

    save = load_save(path)

    assert save["high_score"] == 0  # managed field falls back to default
    assert save["muted"] is False
    assert save["currency"] == 7    # foreign key rides along untouched


def test_load_save_missing_file_falls_back_to_defaults(tmp_path):
    assert load_save(tmp_path / "absent.json") == DEFAULT_SAVE


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",                # corrupt JSON
        "",                         # empty file
        '["a", "list"]',            # wrong container shape
        '{"high_score": "lots"}',   # wrong field type
        '{"high_score": null}',     # null field
    ],
)
def test_load_save_corrupt_or_malformed_falls_back_to_defaults(tmp_path, raw):
    path = tmp_path / "game_save.json"
    path.write_text(raw)
    assert load_save(path) == DEFAULT_SAVE


def test_score_starts_at_zero_with_persisted_high(tmp_path):
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 500, "muted": False})

    score = Score(path)

    assert score.current == 0
    assert score.high == 500


def test_beating_high_score_fires_event_once_and_persists(tmp_path):
    path = tmp_path / "game_save.json"
    score = Score(path)  # fresh save: high score 0

    score.add_score(20)  # first ever points: beats the default high score

    assert sum(e["type"] == "high_score_beaten" for e in read_events(tmp_path)) == 1

    score.add_score(10)  # still inside the beaten run: no duplicate event
    assert sum(e["type"] == "high_score_beaten" for e in read_events(tmp_path)) == 1

    reloaded = Score(path)
    assert reloaded.high == 30
    assert reloaded.current == 0  # a new run starts from zero


def test_scoring_below_high_fires_nothing_and_writes_nothing(tmp_path):
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 500, "muted": False})
    before = path.read_text()

    score = Score(path)
    score.add_score(100)

    assert read_events(tmp_path) == []
    assert path.read_text() == before


def test_handle_collisions_awards_points_through_the_seam(tmp_path):
    """The asteroid_shot branch pays points_for through the Game seam
    (F2 absorbed the F1 Score seam into Game)."""
    pygame.init()
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)

    player = Player(100, 660)  # far from the asteroid: no player hit
    Asteroid(640, 360, 60)     # large rock: 20 points
    Shot(640, 360)             # overlapping: destroys it this sweep

    game = Game(player, asteroids, shots, powerups, save_path=tmp_path / "game_save.json")
    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.score == points_for(60)


def test_hud_text_surface_renders_nonempty():
    """The HUD font must produce real text surfaces under SDL dummy drivers."""
    pygame.init()
    surface = hud_font().render("Score: 42", True, PALETTE["hud_ink"])
    assert surface.get_width() > 0
    assert surface.get_height() > 0


def test_draw_hud_paints_score_pixels_headless():
    """draw_hud blits visible text with no display, with zero or all slots."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    screen.fill(PALETTE["paper"])
    draw_hud(screen, 1234)  # score-only: lives/wave slots still at zero
    samples = [
        screen.get_at((x, y))
        for x in range(HUD_MARGIN, HUD_MARGIN + 200, 4)
        for y in range(HUD_MARGIN, HUD_MARGIN + HUD_FONT_SIZE, 2)
    ]
    assert any(pixel != (*PALETTE["paper"], 255) for pixel in samples)

    # all three slots filled (F2/F3 will pass real values) must not crash
    draw_hud(screen, 1234, lives=3, wave=2)


def test_draw_game_over_paints_overlay_pixels_headless():
    """The game-over overlay blits centered text with no display, with and
    without the new-high-score line."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    screen.fill(PALETTE["paper"])
    draw_game_over(screen, 1234, new_high=True)
    center_x, center_y = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
    samples = [
        screen.get_at((x, y))
        for x in range(center_x - 300, center_x + 300, 8)
        for y in range(center_y - 90, center_y + 90, 8)
    ]
    assert any(pixel != (*PALETTE["paper"], 255) for pixel in samples)

    screen.fill(PALETTE["paper"])
    draw_game_over(screen, 1234, new_high=False)  # no new-high line: no crash
