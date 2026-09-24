"""Tests for explosion particles and screen shake (engagement F5): size-
scaled bursts, lifetime-bounded sparks, and a shake that decays to still
while never touching an entity's position."""

import math
import random

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    PALETTE,
    PARTICLE_LIFETIME_SECONDS,
    PLAYER_DEATH_BURST_INTENSITY,
    SHAKE_LARGE_ASTEROID,
    SHAKE_MAX_MAGNITUDE,
    SHAKE_PLAYER_DEATH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from main import handle_collisions
from particles import Particle, Shake, burst, burst_count
from player import Player
from powerups import PowerUpType
from shot import Shot


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)

    return updatable, drawable, asteroids, shots, powerups, particles


def make_game(tmp_path, player, asteroids, shots, powerups=None, particles=None, shake=None):
    """A Game wired to the given world, saving into tmp_path."""
    return Game(
        player, asteroids, shots, powerups,
        save_path=tmp_path / "game_save.json", particles=particles, shake=shake,
    )


# --- Burst sizing (pure) ------------------------------------------------------


def test_burst_count_scales_with_radius():
    """The pure sizing function: a larger rock dies into a strictly larger
    cloud, and the intensity multiplier scales it further."""
    small, medium, large = (ASTEROID_MIN_RADIUS * k for k in (1, 2, 3))
    assert burst_count(small) < burst_count(medium) < burst_count(large)
    assert burst_count(ASTEROID_MIN_RADIUS, PLAYER_DEATH_BURST_INTENSITY) > burst_count(
        ASTEROID_MAX_RADIUS
    )


def test_burst_spawns_exactly_the_pure_count_at_the_death_site():
    """burst() emits burst_count particles, all born at the burst position."""
    pygame.init()
    _, _, _, _, _, particles = make_groups()
    position = pygame.Vector2(640, 360)

    burst(position, ASTEROID_MIN_RADIUS * 3)

    assert len(particles) == burst_count(ASTEROID_MIN_RADIUS * 3)
    assert all(sprite.position == position for sprite in particles)


def test_burst_directions_and_speeds_are_randomized():
    """A seeded burst spreads its debris: directions differ across sparks and
    speeds land inside the tuned band."""
    pygame.init()
    random.seed(20260924)
    _, _, _, _, _, particles = make_groups()

    burst(pygame.Vector2(640, 360), ASTEROID_MAX_RADIUS)

    directions = {tuple(round(c) for c in sprite.velocity.normalize()) for sprite in particles}
    assert len(directions) > 1, "a burst of identical vectors is a blob, not debris"
    for sprite in particles:
        speed = sprite.velocity.length()
        assert 0 < speed


# --- Particle lifetime and fade -----------------------------------------------


def test_particles_die_exactly_at_lifetime():
    """A spark survives until its lifetime is spent and is gone the frame
    the age reaches it."""
    pygame.init()
    spark = Particle(100, 100, pygame.Vector2(50, 0))

    spark.update(PARTICLE_LIFETIME_SECONDS / 2)
    assert spark.alive()
    spark.update(PARTICLE_LIFETIME_SECONDS / 2)  # age now equals the lifetime
    assert not spark.alive()


def test_particle_fades_by_shrinking_as_life_runs_out():
    """The remaining-life fraction drives the fade: strictly shrinking toward
    zero as the age approaches the lifetime."""
    pygame.init()
    spark = Particle(100, 100, pygame.Vector2(0, 0))
    fractions = [spark.life_fraction]
    step = PARTICLE_LIFETIME_SECONDS / 4
    for _ in range(4):
        spark.update(step)
        fractions.append(spark.life_fraction)

    assert fractions == sorted(fractions, reverse=True)
    assert fractions[0] == pytest.approx(1.0)
    assert fractions[-1] == pytest.approx(0.0)


def test_particle_renders_headless():
    """Drawing a spark is headless-safe (no alpha path) and lands pixels."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    spark = Particle(640, 360, pygame.Vector2(0, 0))

    screen.fill(PALETTE["paper"])
    spark.draw(screen)
    assert screen.get_at((640, 360)) != (*PALETTE["paper"], 255)


# --- Shake decay and the draw-origin-only constraint --------------------------


def test_shake_decays_to_exactly_zero():
    """Magnitude decays monotonically under repeated updates and snaps to a
    hard zero once the decay passes the stop threshold."""
    shake = Shake()
    shake.kick(SHAKE_PLAYER_DEATH)
    magnitudes = []
    dt = 1 / 60
    for _ in range(120):  # two simulated seconds
        shake.update(dt)
        magnitudes.append(shake.magnitude)

    assert magnitudes == sorted(magnitudes, reverse=True)
    assert magnitudes[0] < SHAKE_PLAYER_DEATH  # the very first update already decays
    assert shake.magnitude == 0.0  # exact zero, not forever-diminishing


def test_shake_kick_is_capped():
    """Stacked kicks clamp at the maximum magnitude."""
    shake = Shake()
    for _ in range(10):
        shake.kick(SHAKE_PLAYER_DEATH)
    assert shake.magnitude == SHAKE_MAX_MAGNITUDE


def test_shake_offset_stays_inside_the_current_magnitude():
    """Every offset is at most the current magnitude away from the origin —
    and a still shake offsets nothing at all."""
    random.seed(7)
    shake = Shake()
    assert shake.offset() == (0, 0)

    shake.kick(10.0)
    for _ in range(50):
        x, y = shake.offset()
        assert math.hypot(x, y) <= shake.magnitude + 1e-9


def test_shake_never_changes_any_sprite_position():
    """The critical F5 constraint: applying the shake the way the main loop
    does — entities draw to a world surface, the surface is blitted at
    shake.offset() — leaves every entity's position exactly where it was."""
    pygame.init()
    _, drawable, _, _, _, _ = make_groups()
    sprites = [
        Asteroid(640, 360, 40),
        Asteroid(200, 200, 60),
        Shot(300, 400),
        Player(100, 660),
    ]
    before = [pygame.Vector2(sprite.position) for sprite in sprites]

    shake = Shake()
    shake.kick(SHAKE_PLAYER_DEATH)
    shake.update(1 / 60)
    offset = shake.offset()
    assert offset != (0, 0)  # a real offset is being applied this frame

    # the main-loop application, verbatim: draw to the world, blit shifted
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    world.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(world)
    screen.fill(PALETTE["paper"])
    screen.blit(world, offset)

    for sprite, position in zip(sprites, before):
        assert sprite.position == position


# --- Bursts and kicks through the real paths ----------------------------------


def test_destroyed_rock_bursts_at_any_size_and_large_rocks_kick_the_shake(tmp_path):
    """The sweep's destruction site bursts every size; only a large rock's
    destruction also rocks the screen, mildly below the player-death kick."""
    pygame.init()
    for radius in (ASTEROID_MIN_RADIUS, ASTEROID_MAX_RADIUS):
        _, _, asteroids, shots, powerups, particles = make_groups()
        player = Player(100, 660)  # far from the fight: no player hit
        game = make_game(tmp_path, player, asteroids, shots, powerups)
        shake = Shake()
        Asteroid(640, 360, radius)
        Shot(640, 360)

        handle_collisions(asteroids, shots, player, game, powerups, shake)

        assert len(particles) == burst_count(radius)  # every size bursts
        if radius >= ASTEROID_MAX_RADIUS:
            assert shake.magnitude == pytest.approx(SHAKE_LARGE_ASTEROID)
            assert shake.magnitude < SHAKE_PLAYER_DEATH  # mild, next to a death
        else:
            assert shake.magnitude == 0.0  # small rocks die silently


def test_large_rock_shake_scales_with_its_size():
    """The large-rock kick is proportional to the rock's radius."""
    pygame.init()
    shake = Shake()
    large = ASTEROID_MAX_RADIUS
    shake.kick(SHAKE_LARGE_ASTEROID * large / ASTEROID_MAX_RADIUS)
    assert shake.magnitude == pytest.approx(SHAKE_LARGE_ASTEROID)


def test_player_death_bursts_hard_and_shakes_strong_through_the_real_path(tmp_path):
    """A hit that costs a life bursts a cloud at the hull and kicks a strong
    shake — through Game.player_hit, the one place a life is lost."""
    pygame.init()
    _, _, asteroids, shots, powerups, particles = make_groups()
    player = Player(100, 660)
    shake = Shake()
    game = make_game(tmp_path, player, asteroids, shots, powerups, particles, shake)
    Asteroid(100, 660, 40)  # overlapping the ship

    handle_collisions(asteroids, shots, player, game, powerups, shake)

    assert game.lives == 2  # a real hit: one life gone
    assert len(particles) == burst_count(20, PLAYER_DEATH_BURST_INTENSITY)
    assert shake.magnitude == pytest.approx(SHAKE_PLAYER_DEATH)


def test_player_death_burst_is_larger_than_any_rock_burst(tmp_path):
    """The ship's death cloud outsizes even a large rock's — the deck is
    stacked by intensity, not just radius."""
    assert burst_count(20, PLAYER_DEATH_BURST_INTENSITY) > burst_count(ASTEROID_MAX_RADIUS)


def test_shield_absorbed_hit_neither_bursts_nor_shakes(tmp_path):
    """A shielded hit is neither a death nor a life lost: silent on both
    effect channels, exactly as the absorb skips respawn."""
    pygame.init()
    _, _, asteroids, shots, powerups, particles = make_groups()
    player = Player(100, 660)
    shake = Shake()
    game = make_game(tmp_path, player, asteroids, shots, powerups, particles, shake)
    player.activate_powerup(PowerUpType.SHIELD)
    Asteroid(100, 660, 40)

    handle_collisions(asteroids, shots, player, game, powerups, shake)

    assert game.lives == 3  # absorbed
    assert len(particles) == 0
    assert shake.magnitude == 0.0
