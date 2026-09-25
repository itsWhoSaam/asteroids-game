"""Insanity threats: saucers — the kind table, the spawn clock's wave gate,
real enemy fire, paid kills vs the off-screen cull, and the sweep's hostile
branches.

Failure signatures the tests must catch (spec): saucers minting nothing or
double-paying through the diff; a cull paid as a kill; saucers firing into
the friendly group; wave-1 threats.
"""

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SAUCER_FIRST_WAVE,
    SAUCER_SPAWN_INTERVAL_S,
)
from game import Game
from main import handle_collisions
from player import Player
from saucer import (
    Saucer,
    SaucerScheduler,
    SaucerShot,
    next_saucer_kind,
    saucer_fire_params,
    spawn_side_position,
)
from shot import Shot


def make_world(tmp_path):
    """Groups + Game wired like main(), with the threat groups separate."""
    pygame.init()
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    enemy_shots = pygame.sprite.Group()
    saucers = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    SaucerShot.containers = (enemy_shots, updatable, drawable)
    Saucer.containers = (saucers, drawable)

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.invulnerability_timer = 0.0  # the sweep's hit branch must resolve
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, powerups, saucers, enemy_shots


@pytest.fixture(autouse=True)
def _saucer_containers():
    """Saucer()/SaucerShot() built outside make_world still need groups:
    alive() is pygame's in-a-group check, and take_hit consults it."""
    pygame.init()
    Saucer.containers = (pygame.sprite.Group(), pygame.sprite.Group())
    SaucerShot.containers = (
        pygame.sprite.Group(), pygame.sprite.Group(), pygame.sprite.Group()
    )
    Shot.containers = (
        pygame.sprite.Group(), pygame.sprite.Group(), pygame.sprite.Group()
    )
    yield


# --- the pure kind table -------------------------------------------------------


def test_saucer_fire_params_match_the_table():
    big = saucer_fire_params("big")
    assert big["hp"] == 2
    assert big["points"] == 200
    assert big["spread"] == 3

    small = saucer_fire_params("small")
    assert small["hp"] == 1
    assert small["points"] == 1000
    assert small["spread"] == 1
    # The small saucer is faster and fires faster — that's its whole threat.
    assert small["speed"] > big["speed"]
    assert small["fire_interval"] < big["fire_interval"]


def test_kinds_alternate_forever():
    kinds = [next_saucer_kind(i) for i in range(5)]
    assert kinds == ["big", "small", "big", "small", "big"]


def test_spawn_positions_sit_at_a_side_edge():
    for _ in range(20):
        x, y = spawn_side_position("big")
        assert x < 0 or x > SCREEN_WIDTH  # just outside a side edge
        assert 0 < y < SCREEN_HEIGHT  # vertically on-screen


# --- the spawn clock ------------------------------------------------------------


def test_the_clock_holds_below_the_first_saucer_wave():
    clock = SaucerScheduler()
    # Far past the interval: a wave-1 run is never threatened.
    assert clock.update(1000.0, 1) is None


def test_the_clock_fires_from_wave_two_and_alternates():
    clock = SaucerScheduler()

    assert clock.update(SAUCER_SPAWN_INTERVAL_S, SAUCER_FIRST_WAVE) == "big"
    # The jittered re-arm keeps the next spawn near the interval, never now —
    # so a huge step is guaranteed to cross it.
    assert clock.timer > 0
    assert clock.update(1000.0, SAUCER_FIRST_WAVE) == "small"
    assert clock.timer > 0


def test_the_clock_reset_re_arms():
    clock = SaucerScheduler()
    clock.update(SAUCER_SPAWN_INTERVAL_S, 2)

    clock.reset()
    assert clock.timer == SAUCER_SPAWN_INTERVAL_S


# --- saucer behavior ------------------------------------------------------------


def test_saucer_fire_puts_real_shots_in_the_enemy_group(tmp_path):
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    saucer = Saucer(200, 200, "small")
    saucer.fire_timer = 0.0

    saucer.update(1 / 60, player, enemy_shots)

    assert len(enemy_shots) == 1  # the small kind fires a single aimed shot
    enemy_shot = list(enemy_shots)[0]
    # Aimed at the player: the shot's velocity points from saucer to ship.
    aim = (player.position - saucer.position).normalize()
    assert enemy_shot.velocity.normalize().dot(aim) == pytest.approx(1.0, abs=1e-6)


def test_big_saucer_fires_a_three_way_spread(tmp_path):
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    saucer = Saucer(200, 200, "big")
    saucer.fire_timer = 0.0

    saucer.update(1 / 60, player, enemy_shots)

    assert len(enemy_shots) == 3


def test_a_dead_saucer_never_re_reports(tmp_path):
    saucer = Saucer(200, 200, "small")

    assert saucer.take_hit() is True  # 1 hp: the first shot kills
    assert saucer.take_hit() is False  # never a double pay


def test_off_screen_exit_is_a_cull_not_a_kill(tmp_path):
    """The spec's cull: a saucer that drifts off-screen marks despawned —
    the diff's 'was not destroyed' flag — and never pays a kill."""
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    saucer = Saucer(-70, 300, "big", heading=-1.0)  # already past the cull line

    saucer.update(1 / 60, player, enemy_shots)

    assert saucer.despawned is True
    assert not saucer.alive()


# --- the sweep's hostile branches ------------------------------------------------


def test_player_shots_pay_saucer_kills_through_register_kill(tmp_path):
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    saucer = Saucer(400, 300, "small")
    Shot(400, 300)

    handle_collisions(asteroids, shots, player, game, powerups,
                      saucers=saucers, enemy_shots=enemy_shots)

    assert game.score == 1000  # SAUCER_KINDS["small"]["points"], chain 1 ×1
    assert not saucer.alive()


def test_big_saucer_survives_the_first_shot_and_pays_on_the_second(tmp_path):
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    saucer = Saucer(400, 300, "big")  # 2 hp
    Shot(400, 300)
    handle_collisions(asteroids, shots, player, game, powerups,
                      saucers=saucers, enemy_shots=enemy_shots)
    assert saucer.alive()
    assert game.score == 0  # a soaked shot pays nothing

    Shot(400, 300)
    handle_collisions(asteroids, shots, player, game, powerups,
                      saucers=saucers, enemy_shots=enemy_shots)
    assert not saucer.alive()
    assert game.score == 200


def test_saucer_contact_costs_a_life(tmp_path):
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    saucer = Saucer(player.position.x, player.position.y, "small")
    lives = game.lives

    handle_collisions(asteroids, shots, player, game, powerups,
                      saucers=saucers, enemy_shots=enemy_shots)

    assert game.lives == lives - 1
    assert saucer.alive()  # contact damages the ship, not the saucer


def test_enemy_shots_cost_a_life_and_die(tmp_path):
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    SaucerShot(player.position.x, player.position.y)
    lives = game.lives

    handle_collisions(asteroids, shots, player, game, powerups,
                      saucers=saucers, enemy_shots=enemy_shots)

    assert game.lives == lives - 1
    assert len(enemy_shots) == 0  # the shot dies on impact


def test_enemy_shots_split_asteroids_combo_free(tmp_path):
    """Enemy fire splits rocks through the ordinary take_hit path — but no
    combo, no points: the diff pays its credits, nothing else."""
    game, player, asteroids, shots, powerups, saucers, enemy_shots = make_world(tmp_path)
    big = Asteroid(400, 300, 60)  # two splits from top
    prev_score = game.score
    SaucerShot(400, 300)

    handle_collisions(asteroids, shots, player, game, powerups,
                      saucers=saucers, enemy_shots=enemy_shots)

    assert not big.alive()
    assert len(asteroids) == 2  # the split's two children
    assert game.score == prev_score  # enemy kills never combo
