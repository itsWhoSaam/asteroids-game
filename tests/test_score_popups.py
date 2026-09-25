"""Tests for the distinct score popups: a shot kill's points award floats
its own white '+N pts' over the wreck while credits keep their yellow '+N'
— one FloatingText dt-timer template, two resolved looks, and no economy
math touched.
"""

import pygame

from asteroid import Asteroid
from constants import FLOAT_COLOR, PALETTE, SCORE_COLOR, SCORE_POPUP_OFFSET_Y
from economy import Economy
from game import Game
from hud import points_for
from main import (
    FloatingText,
    destroyed_asteroids,
    float_label,
    handle_collisions,
    popup_style,
)
from player import Player
from shot import Shot


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    floaters = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    FloatingText.containers = (floaters, updatable, drawable)

    return updatable, drawable, asteroids, shots, powerups, floaters


# --- pure label & color resolution ------------------------------------------


def test_points_style_announces_pts_in_warm_white():
    style = popup_style("points", 100)
    assert style.label == "+100 pts"
    assert style.color == SCORE_COLOR
    assert style.color == PALETTE["hud_ink"]  # the palette's warm white


def test_credits_style_keeps_the_existing_look():
    """The credits kind resolves exactly what the float always rendered."""
    style = popup_style("credits", 30.625)
    assert style.label == float_label(30.625) == "+30"
    assert style.color == FLOAT_COLOR


def test_popup_kinds_resolve_distinctly():
    """Same number, different kinds — never the same look."""
    points = popup_style("points", 50)
    credits = popup_style("credits", 50)
    assert points.label != credits.label
    assert points.color != credits.color


def test_points_style_truncates_to_whole_points():
    assert popup_style("points", 30.625).label == "+30 pts"


# --- kill-site integration ---------------------------------------------------


def test_shot_kill_floats_a_score_popup_over_the_wreck(tmp_path):
    """The sweep's points award is accompanied by exactly one white popup at
    the kill site, a head above where the credit float will land."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, powerups, floaters = make_groups()
    try:
        player = Player(100, 660)  # far from the wreck: no player hit
        game = Game(player, asteroids, shots, powerups,
                    save_path=tmp_path / "game_save.json")
        Asteroid(640, 360, 40)  # medium tier → 50 points
        Shot(640, 360)

        handle_collisions(asteroids, shots, player, game, powerups)

        score_popups = [f for f in floaters if f.label.endswith("pts")]
        assert len(score_popups) == 1
        popup = score_popups[0]
        assert popup.label == f"+{points_for(40)} pts"
        assert popup.color == SCORE_COLOR
        assert popup.position.x == 640
        assert popup.position.y == 360 - SCORE_POPUP_OFFSET_Y
        # The award itself is unchanged by the popup.
        assert game.score == points_for(40)
    finally:
        FloatingText.containers = ()


def test_kill_frame_pays_one_credit_float_beside_the_popup(tmp_path):
    """The full kill frame: the destruction diff still mints exactly once
    and floats the yellow credit at the wreck, under the white popup —
    two looks on one FloatingText template, no double pay."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, powerups, floaters = make_groups()
    try:
        player = Player(100, 660)
        game = Game(player, asteroids, shots, powerups,
                    save_path=tmp_path / "game_save.json")
        economy = Economy(save_path=str(tmp_path / "idle_save.json"))
        Asteroid(640, 360, 40)
        Shot(640, 360)

        prev = set(asteroids)  # the main loop snapshots the previous frame
        handle_collisions(asteroids, shots, player, game, powerups)

        destroyed = destroyed_asteroids(prev, asteroids)
        assert len(destroyed) == 1
        for wreck in destroyed:
            payout = economy.mint(wreck.radius)
            style = popup_style("credits", payout)
            FloatingText(wreck.position.x, wreck.position.y, payout,
                         label=style.label, color=style.color)

        assert economy.credits == points_for(40) == 50  # paid once, unchanged

        credit_floats = [f for f in floaters if not f.label.endswith("pts")]
        score_popups = [f for f in floaters if f.label.endswith("pts")]
        assert len(credit_floats) == 1 and len(score_popups) == 1
        credit, popup = credit_floats[0], score_popups[0]
        assert credit.label == f"+{int(50)}"
        assert credit.color == FLOAT_COLOR != popup.color
        assert popup.position.y == credit.position.y - SCORE_POPUP_OFFSET_Y
    finally:
        FloatingText.containers = ()


# --- render smoke ------------------------------------------------------------


def test_both_popup_kinds_draw_headless_smoke():
    """Both kinds render through the shared template onto a plain surface —
    the headless contract (no per-pixel display alpha, no wall clock)."""
    pygame.init()
    floaters = pygame.sprite.Group()
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    FloatingText.containers = (floaters, updatable, drawable)
    try:
        points_style = popup_style("points", 100)
        credits_style = popup_style("credits", 20)
        pts = FloatingText(400, 300, 100,
                           label=points_style.label, color=points_style.color)
        credits = FloatingText(400, 340, 20,
                               label=credits_style.label, color=credits_style.color)

        screen = pygame.Surface((1280, 720))
        pts.draw(screen)
        credits.draw(screen)

        assert pts.surface.get_width() > 0 and credits.surface.get_width() > 0
        # "+100 pts" carries its suffix: strictly wider than the bare "+20".
        assert pts.surface.get_width() > credits.surface.get_width()

        pts.update(0.5)
        assert pts.alive() and pts.position.y < 300  # rising on the dt timer
    finally:
        FloatingText.containers = ()
