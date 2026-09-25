"""Tests for wave milestone rewards (Tier 1): every 5th cleared wave grants
a shield charge plus a flat credit bonus, announced in the banner text.

The trigger is pure (main.milestone_reward) and the grant runs through the
real advance harness (main.maybe_advance_wave), so the tests prove exactly
the divisible-by-5 boundary — and that nothing fires on any other wave.
"""

import json

import pygame
import pytest

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import (
    MILESTONE_CREDIT_BONUS,
    MILESTONE_SHIELD_CHARGES,
    MILESTONE_WAVE_INTERVAL,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import WaveBanner, wave_banner_text
from main import MilestoneReward, maybe_advance_wave, milestone_reward
from player import Player
from shot import Shot


def make_world(tmp_path):
    """Fresh groups + Game + field + economy wired like main(), saving into
    tmp_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = updatable

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    economy = Economy(save_path=tmp_path / "game_save.json")
    return game, field, player, economy


def populate(field):
    """A real spawn, as the field's update() makes one: joins the group and
    raises the populated guard, without update()'s randomness."""
    return field.spawn(60, pygame.Vector2(100, 100), pygame.Vector2(10, 0))


def clear_and_advance(game, field, banner, player, economy):
    """One full wave cycle: a rock spawns, dies (what split()/culling do),
    and the cleared field advances through the real harness. The run starts
    at wave 1, so each cycle ticks exactly one wave."""
    populate(field).kill()
    maybe_advance_wave(game, field, banner, player, economy)


def advance_to_wave(game, field, banner, player, economy, target):
    """Clear+advance cycles until the run reaches `target`."""
    while game.wave < target:
        clear_and_advance(game, field, banner, player, economy)
    assert game.wave == target


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- the pure trigger (main.milestone_reward) ---


@pytest.mark.parametrize("wave", [5, 10, 15, 50, 500])
def test_milestone_reward_fires_exactly_on_divisible_waves(wave):
    reward = milestone_reward(wave)
    assert reward == MilestoneReward(
        shield_charges=MILESTONE_SHIELD_CHARGES,
        credits=MILESTONE_CREDIT_BONUS,
    )


@pytest.mark.parametrize("wave", [1, 2, 3, 4, 6, 9, 11, 14, 16, 49, 51, 99, 101])
def test_milestone_reward_skips_every_other_wave(wave):
    assert milestone_reward(wave) is None


def test_milestone_interval_constant_drives_the_trigger():
    """The interval constant is the trigger's whole story: one step past a
    multiple pays none, the multiple itself pays the grant."""
    assert milestone_reward(MILESTONE_WAVE_INTERVAL) is not None
    assert milestone_reward(MILESTONE_WAVE_INTERVAL + 1) is None
    assert milestone_reward(2 * MILESTONE_WAVE_INTERVAL) is not None


# --- the grant through the real advance harness ---


def test_fifth_cleared_wave_grants_shield_and_credits(tmp_path):
    """Advance wave by wave to 5: the grant lands exactly on wave 5, and no
    earlier wave stocks anything."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()

    advance_to_wave(game, field, banner, player, economy, 4)
    assert player.shield_hits == 0
    assert economy.credits == 0.0

    clear_and_advance(game, field, banner, player, economy)
    assert game.wave == 5
    assert player.shield_hits == MILESTONE_SHIELD_CHARGES
    assert economy.credits == MILESTONE_CREDIT_BONUS


def test_grant_does_not_repeat_on_the_next_wave(tmp_path):
    """Wave 6 pays nothing: one grant per milestone, not a running drip."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()

    advance_to_wave(game, field, banner, player, economy, 5)
    assert player.shield_hits == MILESTONE_SHIELD_CHARGES

    clear_and_advance(game, field, banner, player, economy)
    assert game.wave == 6
    assert player.shield_hits == MILESTONE_SHIELD_CHARGES  # unchanged
    assert economy.credits == MILESTONE_CREDIT_BONUS  # unchanged


def test_blocked_advance_grants_nothing(tmp_path):
    """The populated guard must hold the whole grant back, not just the
    wave tick."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    game.wave = 4  # one clear away from the milestone
    banner = WaveBanner()
    populate(field)  # alive in the group: the wave is not cleared

    maybe_advance_wave(game, field, banner, player, economy)

    assert game.wave == 4
    assert player.shield_hits == 0
    assert economy.credits == 0.0


def test_no_grant_during_game_over(tmp_path):
    """Game over advances nothing, so it pays nothing either."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"
    game.wave = 4
    populate(field).kill()  # even a cleared populated field must not advance

    maybe_advance_wave(game, field, WaveBanner(), player, economy)

    assert game.wave == 4
    assert player.shield_hits == 0
    assert economy.credits == 0.0


def test_pinned_three_argument_call_still_advances(tmp_path):
    """Tests and the balance sim call maybe_advance_wave with three args;
    the optional kwargs must keep that shape working (no grant seams, no
    crash, wave still ticks)."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()

    advance_to_wave(game, field, banner, player, economy, 4)
    populate(field).kill()
    maybe_advance_wave(game, field, banner)  # the milestone wave, no seams

    assert game.wave == 5
    assert player.shield_hits == 0  # nothing granted: no seams passed
    assert economy.credits == 0.0


# --- the shield charge is run state with the right lifetime ---


def test_milestone_shield_survives_until_spent(tmp_path):
    """The grant is a kept charge, not a timed window: seconds of ticking
    expire nothing (a drop-shield's clock would have wiped it)."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()
    advance_to_wave(game, field, banner, player, economy, 5)
    assert player.shield_hits == MILESTONE_SHIELD_CHARGES

    player.update(10.0)  # many seconds of ticking: no clock to expire

    assert player.shield_hits == MILESTONE_SHIELD_CHARGES
    assert player.shielded


def test_milestone_shield_is_run_state_a_restart_clears(tmp_path):
    """No new reset wiring: the charge lives in the same pool clear_powerups
    wipes, so the restart hooks (game.restart, the R branch) clear it free."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()
    advance_to_wave(game, field, banner, player, economy, 5)
    assert player.shielded

    game.restart()  # what both restart hooks run

    assert player.shield_hits == 0


def test_milestone_credits_survive_a_restart(tmp_path):
    """The bonus pays the idle ledger — meta-progression, not run state: a
    restart wipes the run but keeps the earned credits."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()
    advance_to_wave(game, field, banner, player, economy, 5)
    assert economy.credits == MILESTONE_CREDIT_BONUS

    game.restart()

    assert economy.credits == MILESTONE_CREDIT_BONUS


# --- the banner announcement ---


def test_milestone_banner_text_names_the_grant():
    assert wave_banner_text(5, milestone_credits=500.0) == (
        "MILESTONE WAVE 5 - SHIELD +500 CR"
    )


def test_plain_banner_text_when_no_milestone():
    assert wave_banner_text(3) == "WAVE 3"
    assert wave_banner_text(3, milestone_credits=None) == "WAVE 3"


def test_milestone_wave_flashes_the_announcement(tmp_path):
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()
    advance_to_wave(game, field, banner, player, economy, 4)

    clear_and_advance(game, field, banner, player, economy)

    assert game.wave == 5
    assert banner.visible
    assert banner.text == "MILESTONE WAVE 5 - SHIELD +500 CR"


def test_milestone_banner_paints_centered_pixels_headless(tmp_path):
    """Render smoke (the wave-banner precedent): the longer milestone line
    paints around the banner anchor under dummy drivers."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()
    advance_to_wave(game, field, banner, player, economy, 5)

    screen.fill(PALETTE["paper"])
    banner.draw(screen)
    center_x, center_y = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 3
    samples = [
        screen.get_at((x, y))
        for x in range(center_x - 400, center_x + 400, 8)
        for y in range(center_y - 40, center_y + 40, 4)
    ]
    assert any(pixel != (*PALETTE["paper"], 255) for pixel in samples)


def test_milestone_reward_event_logged_once(tmp_path):
    """The grant rides the free-form logger so the balance sim and run
    reviews can see milestone payouts."""
    pygame.init()
    game, field, player, economy = make_world(tmp_path)
    banner = WaveBanner()
    advance_to_wave(game, field, banner, player, economy, 5)
    clear_and_advance(game, field, banner, player, economy)  # wave 6: nothing

    milestone = [e for e in read_events(tmp_path) if e["type"] == "milestone_reward"]
    assert len(milestone) == 1
    assert milestone[0]["wave"] == 5
    assert milestone[0]["shield_charges"] == MILESTONE_SHIELD_CHARGES
    assert milestone[0]["credits"] == MILESTONE_CREDIT_BONUS
