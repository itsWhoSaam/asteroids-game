"""Tests for run stats + the end-of-run summary (run-stats PR).

The counters are pure bumps on a RunStats instance, so the first block
drives a bare one with synthetic events and pins every number and every
summary line. The wiring block proves the counters climb from the real
instrumentation points — the ship's trigger, the collision sweep, the
mint poll, the wave harness — and that BOTH restart hooks (Game.restart
and main.restart_run, what the R key runs) zero them in place. The last
block renders the game-over summary headless and asserts pixels.
"""

import json

import pygame
import pytest

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import (
    CHIP_HEALTH_PER_TIER,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import WaveBanner, draw_game_over, draw_run_summary
from main import (
    handle_collisions,
    maybe_advance_wave,
    mint_destructions,
    restart_run,
)
from player import Player
from powerups import PowerUpType
from shot import Shot
from stats import SOURCE_CLICK, SOURCE_IDLE, RunStats, tier_for


def make_world(tmp_path):
    """Fresh groups + Game + field + economy wired like main(), saving into
    tmp_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = updatable

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    economy = Economy(save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, powerups, field, economy


# --- the pure counters (synthetic events on a bare instance) ---------------


def test_fresh_stats_are_all_zero():
    stats = RunStats()
    assert stats.shots_fired == 0
    assert stats.shots_hit == 0
    assert stats.destroyed == {"small": 0, "medium": 0, "large": 0}
    assert stats.waves_survived == 0
    assert stats.credits_idle == 0.0
    assert stats.credits_click == 0.0
    assert stats.credits_earned == 0.0
    assert stats.accuracy() is None


def test_record_shot_counts_bullets():
    stats = RunStats()
    for _ in range(3):
        stats.record_shot()
    assert stats.shots_fired == 3
    assert stats.accuracy() == 0.0  # fired and missed everything: 0%, not None


def test_accuracy_is_hits_over_fired():
    stats = RunStats()
    for _ in range(4):
        stats.record_shot()
    stats.record_hit()
    assert stats.accuracy() == pytest.approx(0.25)
    stats.record_hit()
    stats.record_hit()
    assert stats.accuracy() == pytest.approx(0.75)


def test_tier_for_mirrors_the_points_banding():
    """Same banding points_for pays on: small 1x, medium 2x, large 3x+."""
    assert tier_for(20) == "small"
    assert tier_for(30) == "small"
    assert tier_for(40) == "medium"
    assert tier_for(50) == "medium"
    assert tier_for(60) == "large"
    assert tier_for(80) == "large"


def test_record_destroyed_bands_and_accumulates():
    stats = RunStats()
    stats.record_destroyed(60)  # large
    stats.record_destroyed(40)  # medium
    stats.record_destroyed(20)  # small
    stats.record_destroyed(20)  # small again
    assert stats.destroyed == {"small": 2, "medium": 1, "large": 1}


def test_record_credits_splits_click_from_idle():
    stats = RunStats()
    stats.record_credits(1250.0, SOURCE_IDLE)
    stats.record_credits(250.0, SOURCE_CLICK)
    assert stats.credits_idle == 1250.0
    assert stats.credits_click == 250.0
    assert stats.credits_earned == 1500.0


def test_record_credits_unknown_source_lands_idle():
    """Only a click kill pays the click bucket; any other attribution —
    today's shots/drones/nukes, tomorrow's — is idle-economy income."""
    stats = RunStats()
    stats.record_credits(100.0, "not-a-click")
    assert stats.credits_idle == 100.0
    assert stats.credits_click == 0.0


def test_summary_lines_exact_wording():
    stats = RunStats()
    for _ in range(3):
        stats.record_shot()
    stats.record_hit()
    stats.record_destroyed(20)
    stats.record_destroyed(40)
    stats.record_destroyed(60)
    for _ in range(3):
        stats.record_wave_cleared()
    stats.record_credits(1250.0, SOURCE_IDLE)
    stats.record_credits(250.0, SOURCE_CLICK)

    assert stats.summary_lines() == [
        "Shots: 1/3 hit (33%)",
        "Rocks destroyed: 1 small, 1 medium, 1 large",
        "Waves survived: 3",
        "Credits earned: 1500 (idle 1250, click 250)",
    ]


def test_summary_lines_without_shots_reads_zero_over_zero():
    """A passive run (idle layer only) is not a 0% accuracy one."""
    stats = RunStats()
    assert stats.summary_lines()[0] == "Shots: 0/0 hit"


def test_reset_zeroes_in_place():
    """reset() must never rebind: the player records against the very
    instance Game handed it, so a rebind would orphan the counters."""
    stats = RunStats()
    stats.record_shot()
    stats.record_destroyed(60)
    stats.record_credits(500.0, SOURCE_CLICK)
    stats.record_wave_cleared()
    holder = stats

    stats.reset()

    assert holder is stats  # same object, zeroed — not a fresh instance
    assert stats.shots_fired == 0
    assert stats.shots_hit == 0
    assert stats.destroyed == {"small": 0, "medium": 0, "large": 0}
    assert stats.waves_survived == 0
    assert stats.credits_idle == 0.0
    assert stats.credits_click == 0.0


# --- the wiring (real instrumentation points) -------------------------------


def test_game_owns_stats_and_hands_them_to_the_player(tmp_path):
    pygame.init()
    game, player, *_ = make_world(tmp_path)
    assert isinstance(game.stats, RunStats)
    assert player.stats is game.stats  # one instance, both holders
    assert game.stats.shots_fired == 0


def test_player_shots_are_counted_per_bullet(tmp_path):
    pygame.init()
    game, player, *_ = make_world(tmp_path)

    player.shoot()
    assert game.stats.shots_fired == 1

    player.activate_powerup(PowerUpType.TRIPLE)
    player.shot_cooldown_timer = 0  # the cooldown re-arms after the volley
    player.shoot()
    assert game.stats.shots_fired == 4  # three more: the TRIPLE volley


def test_sweep_counts_player_shot_hits(tmp_path):
    pygame.init()
    game, player, asteroids, shots, powerups, *_ = make_world(tmp_path)
    Asteroid(640, 360, 40)
    shot = Shot(640, 360)
    assert not shot.from_drone  # the player's own bullet by default

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.stats.shots_hit == 1


def test_drone_shots_fly_tagged_and_skip_the_accuracy_read(tmp_path):
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    Asteroid(640, 360, 40)
    from drones import DroneTurret

    turret = DroneTurret(0, 1)
    turret.fire(player, asteroids, shots)
    shot = next(iter(shots))
    assert shot.from_drone  # tagged at the turret's fire site
    shot.position = pygame.Vector2(640, 360)  # overlap for the sweep

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.stats.shots_hit == 0  # turret fire is not the player's trigger
    assert len(asteroids) == 2  # but the rock still split: the pipeline is shared


def test_a_rock_chipped_partway_then_shot_pays_idle(tmp_path):
    """Attribution follows the killer, not the chip history: the sweep
    re-attributes before the split, so a chipped rock finished by a shot
    never lands in the click bucket."""
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    rock = Asteroid(640, 360, 20)  # small: one chip's worth ends it
    rock.take_chip(CHIP_HEALTH_PER_TIER * 0.5)  # chipped, still alive
    Shot(640, 360)
    prev = set(asteroids)  # last frame's field: the rock was on it

    handle_collisions(asteroids, shots, player, game, powerups)
    paid = mint_destructions(prev, asteroids, economy, game.stats)

    assert rock.killed_by == SOURCE_IDLE
    assert len(paid) == 1
    assert game.stats.credits_idle == 100.0  # points_for(small)
    assert game.stats.credits_click == 0.0


def test_a_click_kill_pays_the_click_bucket(tmp_path):
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    rock = Asteroid(640, 360, 20)
    prev = set(asteroids)  # last frame's field: the rock was on it

    rock.take_chip(CHIP_HEALTH_PER_TIER)  # the click that kills
    paid = mint_destructions(prev, asteroids, economy, game.stats)

    assert rock.killed_by == SOURCE_CLICK
    assert len(paid) == 1
    assert game.stats.credits_click == 100.0
    assert game.stats.credits_idle == 0.0
    assert game.stats.destroyed["small"] == 1


def test_mint_poll_records_tier_and_idle_credits_for_shot_kills(tmp_path):
    """The frame diff is the one place every destruction source surfaces:
    a shot-killed medium rock pays the ledger and books its tier."""
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    Asteroid(640, 360, 40)  # medium parent; its split children are small
    prev = set(asteroids)

    Shot(640, 360)
    handle_collisions(asteroids, shots, player, game, powerups)
    paid = mint_destructions(prev, asteroids, economy, game.stats)

    assert len(paid) == 1  # the parent only — split children never pay twice
    wreck, payout = paid[0]
    assert wreck.radius == 40
    assert payout == pytest.approx(50.0)  # points_for(medium), income 1.0
    assert economy.credits == pytest.approx(50.0)
    assert game.stats.destroyed["medium"] == 1
    assert game.stats.destroyed["small"] == 0  # the children were born, not killed
    assert game.stats.credits_idle == pytest.approx(50.0)


def test_culls_pay_the_poll_nothing(tmp_path):
    """The despawned flag keeps restarts and off-screen drift out of the
    destruction counters, same as out of the ledger."""
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    rock = Asteroid(640, 360, 40)
    rock.despawned = True
    rock.kill()
    prev = set(asteroids)

    paid = mint_destructions(prev, asteroids, economy, game.stats)

    assert paid == []
    assert game.stats.destroyed == {"small": 0, "medium": 0, "large": 0}
    assert game.stats.credits_earned == 0.0


def test_wave_advances_book_as_waves_survived(tmp_path):
    """The wave harness records through the same maybe_advance_wave the
    milestone rewards ride; game over advances nothing."""
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    banner = WaveBanner()

    field.spawn(60, pygame.Vector2(100, 100), pygame.Vector2(10, 0)).kill()
    maybe_advance_wave(game, field, banner)
    assert game.wave == 2
    assert game.stats.waves_survived == 1

    for _ in range(3):
        game.player_hit()  # the run ends mid-wave-2
    assert game.state == "game_over"
    field.spawn(60, pygame.Vector2(100, 100), pygame.Vector2(10, 0)).kill()
    maybe_advance_wave(game, field, banner)
    assert game.stats.waves_survived == 1  # unchanged: game over advances nothing


# --- both restart hooks zero the counters -----------------------------------


def test_restart_hook_one_game_restart_zeroes_stats_in_place(tmp_path):
    """Game.restart is the shared reset both R paths funnel into."""
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    stats = game.stats
    stats.record_shot()
    stats.record_hit()
    stats.record_destroyed(60)
    stats.record_credits(250.0, SOURCE_CLICK)
    stats.record_wave_cleared()

    game.restart()

    assert game.stats is stats  # in place: the player still holds this one
    assert player.stats is stats
    assert stats.shots_fired == 0
    assert stats.shots_hit == 0
    assert stats.destroyed == {"small": 0, "medium": 0, "large": 0}
    assert stats.waves_survived == 0
    assert stats.credits_earned == 0.0


def test_restart_hook_two_r_branch_zeroes_stats(tmp_path):
    """main.restart_run is exactly what the R key runs (game-over screen and
    pause overlay alike): a full run's counters die with it."""
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    banner = WaveBanner()
    game.stats.record_shot()
    game.stats.record_hit()
    game.stats.record_destroyed(20)
    game.stats.record_credits(100.0, SOURCE_IDLE)
    game.stats.record_wave_cleared()
    Asteroid(640, 360, 40)

    restart_run(game, economy, field, banner, asteroids)

    stats = game.stats
    assert stats.shots_fired == 0
    assert stats.shots_hit == 0
    assert stats.destroyed == {"small": 0, "medium": 0, "large": 0}
    assert stats.waves_survived == 0
    assert stats.credits_earned == 0.0
    assert player.stats is stats  # the fresh run records into the same instance
    assert len(asteroids) == 0  # the world cleared with the counters


def test_stats_never_reach_the_save_file(tmp_path):
    """Run-scoped only: a full run with counters climbing and a game over
    must leave no stats key in game_save.json — the save merge contract
    carries high_score/muted/volume/idle_* and nothing else."""
    pygame.init()
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    player.shoot()
    game.stats.record_destroyed(20)
    game.stats.record_credits(100.0, SOURCE_IDLE)
    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"
    economy.save()  # the ledger's own autosave, stats nowhere in it

    data = json.loads((tmp_path / "game_save.json").read_text())
    assert not any("stat" in key for key in data)


# --- the game-over summary renders headless ---------------------------------


def test_summary_block_paints_under_the_game_over_prompt(tmp_path):
    """Render smoke (the wave-banner precedent): the summary block paints
    below the game-over overlay's worst case, above the shop panel's edge,
    under the dummy drivers."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    game, player, asteroids, shots, powerups, field, economy = make_world(tmp_path)
    for _ in range(3):
        player.shoot()
        player.shot_cooldown_timer = 0
    game.stats.record_hit()
    game.stats.record_destroyed(60)
    game.stats.record_credits(20.0, SOURCE_IDLE)
    game.stats.record_wave_cleared()
    for _ in range(3):
        game.player_hit()  # run over: the overlay branch renders the block

    screen.fill(PALETTE["paper"])
    draw_game_over(screen, game.score, new_high=game.new_high)
    draw_run_summary(screen, game.stats)

    # The band between the game-over prompt (bottom ~452) and the shop panel
    # (top 656): the summary block's seat, the game-over lines never reach it.
    samples = [
        screen.get_at((x, y))
        for y in range(470, 656, 4)
        for x in range(340, 940, 8)
    ]
    assert any(pixel != (*PALETTE["paper"], 255) for pixel in samples)


def test_summary_block_renders_a_passive_run(tmp_path):
    """Zero every counter — no shots, no kills, wave 1 — and the block
    still renders: no division by zero, no crash, pixels on screen."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    game, player, *_ = make_world(tmp_path)
    for _ in range(3):
        game.player_hit()

    screen.fill(PALETTE["paper"])
    draw_run_summary(screen, game.stats)

    samples = [
        screen.get_at((x, y))
        for y in range(470, 656, 4)
        for x in range(340, 940, 8)
    ]
    assert any(pixel != (*PALETTE["paper"], 255) for pixel in samples)
