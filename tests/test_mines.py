"""Mine asteroids (Tier 3): pure blast math, the armed-spawn roll, the
blinking marker, and the detonation through the sweep — neighbors split
and mint, the ship's hit rides the standard player-hit flow.

Failure signatures the tests must catch (spec): a blast that kills
without minting (a second destruction path), a blast that ignores
invulnerability, a mine that splits into baby mines, and a spawn roll
whose boundary drifts with float luck.
"""

import random

import pygame
import pytest

from asteroid import (
    Asteroid,
    Mine,
    blast_victims,
    in_blast_radius,
    mine_marker_on,
    mine_spawn_rolls_in,
)
from asteroidfield import AsteroidField
from constants import (
    ASTEROID_MIN_RADIUS,
    MINE_BLAST_RADIUS,
    MINE_MARKER_COLOR,
    MINE_SPAWN_CHANCE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from main import HitStop, detonate_mine, handle_collisions, mint_destructions
from particles import Shake
from player import Player
from shot import Shot


def make_world(tmp_path):
    """Fresh groups + Game + field wired like main(), saving into tmp_path."""
    pygame.init()
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = (updatable, drawable)

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    return game, field, player, asteroids, shots, powerups


@pytest.fixture(autouse=True)
def _mine_containers():
    """Mine/Asteroid bodies built outside make_world still need groups:
    alive() is pygame's in-a-group check, and the victim selection and
    take_hit both consult it."""
    pygame.init()
    Asteroid.containers = (
        pygame.sprite.Group(), pygame.sprite.Group(), pygame.sprite.Group()
    )
    yield


# --- pure blast math -----------------------------------------------------------


def test_in_blast_radius_rim_is_inclusive():
    center = pygame.Vector2(0, 0)
    assert in_blast_radius(center, pygame.Vector2(MINE_BLAST_RADIUS, 0),
                           MINE_BLAST_RADIUS)  # exactly on the rim: inside
    assert in_blast_radius(center, pygame.Vector2(0, 0), MINE_BLAST_RADIUS)
    assert not in_blast_radius(
        center, pygame.Vector2(MINE_BLAST_RADIUS + 1, 0), MINE_BLAST_RADIUS
    )


def test_blast_victims_select_only_live_neighbors_within_radius():
    center = pygame.Vector2(400, 300)
    inside = Asteroid(450, 300, ASTEROID_MIN_RADIUS)      # 50 px away
    outside = Asteroid(400 + MINE_BLAST_RADIUS + 50, 300, ASTEROID_MIN_RADIUS)

    victims = blast_victims([inside, outside], center, MINE_BLAST_RADIUS)

    assert inside in victims and outside not in victims


def test_blast_victims_skip_the_dead_and_the_detonating_mine():
    center = pygame.Vector2(400, 300)
    mine = Mine(400, 300, ASTEROID_MIN_RADIUS)  # sits at the blast's center
    inside = Asteroid(450, 300, ASTEROID_MIN_RADIUS)
    dead = Asteroid(410, 300, ASTEROID_MIN_RADIUS)
    dead.kill()

    victims = blast_victims([mine, inside, dead], center, MINE_BLAST_RADIUS,
                            exclude=mine)

    assert victims == [inside]


# --- the armed-spawn roll and the blink ----------------------------------------


def test_mine_spawn_roll_strict_threshold():
    assert mine_spawn_rolls_in(0.0)
    assert mine_spawn_rolls_in(MINE_SPAWN_CHANCE - 0.001)
    assert not mine_spawn_rolls_in(MINE_SPAWN_CHANCE)  # exactly at: a rock
    assert not mine_spawn_rolls_in(0.999)


def test_field_arms_mines_on_the_roll(tmp_path, monkeypatch):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    field.start_wave()
    monkeypatch.setattr(random, "random", lambda: 0.0)  # always a mine

    field.update(0.9)  # one spawn tick past wave 1's 0.8 s interval

    assert len(asteroids) == 1
    assert isinstance(list(asteroids)[0], Mine)
    assert field.spawned_this_wave == 1  # the mine counts as a spawned rock


def test_field_spawns_plain_rocks_when_the_roll_misses(tmp_path, monkeypatch):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    field.start_wave()
    monkeypatch.setattr(random, "random", lambda: 0.999)

    field.update(0.9)

    assert len(asteroids) == 1
    assert not isinstance(list(asteroids)[0], Mine)


def test_marker_blink_square_wave():
    assert mine_marker_on(0.0)  # born lit
    period = 1.0 / 3.0  # MINE_MARKER_BLINK_HZ
    assert mine_marker_on(period)  # wrapped back to the lit half
    assert not mine_marker_on(period * 0.75)  # the dark half
    assert mine_marker_on(period * 2 + period / 4)


def test_mine_draw_reads_dark_and_blinks_headless_safe():
    pygame.init()
    screen = pygame.Surface((100, 100))
    mine = Mine(50, 50, ASTEROID_MIN_RADIUS)

    screen.fill((23, 18, 58))  # the paper
    mine.blink_clock = 0.0  # lit half of the square wave
    mine.draw(screen)
    lit = screen.get_at((50, 50))
    assert (lit.r, lit.g, lit.b) == MINE_MARKER_COLOR  # the danger marker

    screen.fill((23, 18, 58))
    mine.blink_clock = 0.25  # the dark half (period 1/3 s)
    mine.draw(screen)
    hull = screen.get_at((50, 50))
    assert (hull.r, hull.g, hull.b) == (44, 40, 62)  # the dark hull, not a tier hue


# --- the variant's death ---------------------------------------------------------


def test_mine_split_kills_without_children():
    mine = Mine(400, 300, ASTEROID_MIN_RADIUS * 2)

    mine.split()

    assert not mine.alive()
    assert len(Asteroid.containers[0]) == 0  # no baby mines, ever


def test_chip_killing_a_mine_does_not_detonate():
    """Only shots set a mine off: the click path kills it without a blast —
    a careful defusal, and the idle loop stays free of blast hits."""
    mine = Mine(400, 300, ASTEROID_MIN_RADIUS)
    neighbor = Asteroid(450, 300, ASTEROID_MIN_RADIUS)

    assert mine.take_chip(10_000) is True
    assert not mine.alive()
    assert neighbor.alive()  # no blast swept the neighbor away


# --- the detonation through the sweep (integration) ------------------------------


def test_shooting_a_mine_splits_neighbors_and_mints(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    player.position = pygame.Vector2(100, 660)  # clear of the blast
    player.invulnerability_timer = 0.0
    economy = Economy(save_path=tmp_path / "economy_save.json")

    mine = Mine(640, 360, ASTEROID_MIN_RADIUS)
    neighbor = Asteroid(700, 360, ASTEROID_MIN_RADIUS * 2)  # 60 px: inside
    outside = Asteroid(640 + MINE_BLAST_RADIUS + 80, 360, ASTEROID_MIN_RADIUS)
    prev = set(asteroids)
    Shot(640, 360)  # overlapping the mine

    handle_collisions(asteroids, shots, player, game, powerups)

    assert not mine.alive()      # the shot killed it
    assert not neighbor.alive()  # the blast split it
    assert outside.alive()       # beyond the rim: untouched
    children = [rock for rock in asteroids if rock not in (mine, neighbor, outside)]
    assert len(children) == 2    # the neighbor's ordinary split children
    assert all(isinstance(child, Asteroid) and not isinstance(child, Mine)
               for child in children)

    # Economy integrity: both kills surface through the ONE destruction
    # diff and mint exactly once — no kill path bypassed split().
    paid = mint_destructions(prev, asteroids, economy, game.stats)
    wrecks = [wreck for wreck, _ in paid]
    assert mine in wrecks and neighbor in wrecks and len(wrecks) == 2
    assert not any(wreck.despawned for wreck in wrecks)
    assert economy.credits == sum(payout for _, payout in paid) == 100 + 50
    # Blast victims pay no score (combo-free, like the nuke): the mine's
    # own shot kill is the only points award on the frame.
    assert game.score == 100  # points_for(ASTEROID_MIN_RADIUS)


def test_a_drone_tagged_shot_detonates_the_mine_too(tmp_path):
    """Drone fire rides the same friendly sweep — a turret setting off a
    mine is the same detonation, not a second path."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    player.position = pygame.Vector2(100, 660)
    mine = Mine(640, 360, ASTEROID_MIN_RADIUS)
    neighbor = Asteroid(700, 360, ASTEROID_MIN_RADIUS * 2)
    Shot(640, 360).from_drone = True

    handle_collisions(asteroids, shots, player, game, powerups)

    assert not mine.alive() and not neighbor.alive()


# --- the ship inside the blast: the standard player-hit flow ----------------------


def test_blast_reaches_the_ship_through_player_hit(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    player.invulnerability_timer = 0.0
    mine = Mine(640, 360, ASTEROID_MIN_RADIUS)
    player.position = pygame.Vector2(640 + MINE_BLAST_RADIUS - 10, 360)

    detonate_mine(mine, asteroids, player, game)  # direct: the helper, no sweep

    assert game.lives == 2  # the standard hit: one life, respawn, i-frames
    assert player.invulnerable


def test_blast_honors_invulnerability(tmp_path):
    """A respawning ship may sit ON the mine for the grace window: the
    detonation under it costs nothing, like every other hazard."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    player.respawn()  # grace on, ship at center
    mine = Mine(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2, ASTEROID_MIN_RADIUS)

    detonate_mine(mine, asteroids, player, game)

    assert game.lives == 3
    assert game.state == "playing"


def test_blast_honors_game_over_state(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.lives = 0
    game.state = "game_over"
    mine = Mine(640, 360, ASTEROID_MIN_RADIUS)
    player.position = pygame.Vector2(640, 360 + 10)  # inside the radius

    detonate_mine(mine, asteroids, player, game)

    assert game.lives == 0
    assert game.state == "game_over"


def test_a_blast_kick_rocks_the_screen_and_freezes_the_frame(tmp_path):
    """The feel wiring: blast kills buy the hit-stop beat and the blast
    kicks the shake — the nuke's feel, scoped to one radius."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    player.position = pygame.Vector2(100, 660)
    shake = Shake()
    hit_stop = HitStop()
    mine = Mine(640, 360, ASTEROID_MIN_RADIUS)
    Asteroid(700, 360, ASTEROID_MIN_RADIUS * 2)  # one neighbor to lose

    detonate_mine(mine, asteroids, player, game, shake=shake, hit_stop=hit_stop)

    assert shake.magnitude > 0
    assert hit_stop.remaining > 0
