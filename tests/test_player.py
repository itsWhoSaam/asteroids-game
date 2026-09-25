"""Tests for Player respawn and the grace-window blink (engagement F2)."""

import pygame

from constants import (
    PALETTE,
    PLAYER_BLINK_HZ,
    PLAYER_INVULNERABILITY_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from player import Player


def nonbackground_samples(surface):
    """Pixels sampled across the ship's bounding box that are not background."""
    box = [
        surface.get_at((x, y))
        for x in range(600, 681, 4)
        for y in range(320, 401, 4)
    ]
    return [pixel for pixel in box if pixel != (*PALETTE["paper"], 255)]


def test_respawn_centers_zeroes_velocity_and_grants_the_window():
    pygame.init()
    player = Player(100, 660)
    player.velocity = pygame.Vector2(90, 90)

    player.respawn()

    assert player.position == pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    assert player.velocity == pygame.Vector2(0, 0)
    assert player.invulnerability_timer == PLAYER_INVULNERABILITY_SECONDS


def test_invulnerability_decays_with_dt_like_other_timers():
    pygame.init()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.respawn()

    player.update(PLAYER_INVULNERABILITY_SECONDS / 2)
    assert player.invulnerable

    player.update(PLAYER_INVULNERABILITY_SECONDS)  # past the window
    assert not player.invulnerable


def test_blink_hides_the_ship_on_alternate_half_cycles():
    """The grace-window blink toggles visibility at PLAYER_BLINK_HZ while the
    ship is invulnerable — a respawning ship flickers instead of hiding."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    visible = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    visible.invulnerability_timer = 2.0  # first half-cycle: drawn
    screen.fill(PALETTE["paper"])
    visible.draw(screen)
    assert nonbackground_samples(screen)

    hidden = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    hidden.invulnerability_timer = 2.0 - 0.5 / PLAYER_BLINK_HZ  # second half-cycle
    screen.fill(PALETTE["paper"])
    hidden.draw(screen)
    assert nonbackground_samples(screen) == []


def test_blink_ends_when_the_window_expires():
    """Once invulnerability is gone the ship always draws, whatever the timer."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.invulnerability_timer = -1.25  # long expired, mid "hidden" phase

    screen.fill(PALETTE["paper"])
    player.draw(screen)

    assert nonbackground_samples(screen)
