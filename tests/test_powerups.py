"""Tests for timed power-ups (engagement F4): the pure drop rolls, pickup
collection through the sweep, timed effects and their expiry, and the
shield's single-use absorb."""

import json
import random

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    PALETTE,
    PLAYER_RADIUS,
    PLAYER_SHOOT_COOLDOWN_SECONDS,
    POWERUP_DROP_CHANCE,
    POWERUP_DURATION_S,
    POWERUP_RADIUS,
    POWERUP_RAPID_COOLDOWN_MULT,
    POWERUP_SHIELD_HITS,
    POWERUP_SHIELD_RING_GAP,
    POWERUP_TRIPLE_SPREAD,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from main import handle_collisions
from player import Player
from powerups import PowerUp, PowerUpType, drops_powerup, pick_type
from shot import Shot


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)

    return updatable, drawable, asteroids, shots, powerups


def make_game(tmp_path, player, asteroids, shots, powerups):
    """A Game wired to the given world, saving into tmp_path."""
    return Game(player, asteroids, shots, powerups, save_path=tmp_path / "game_save.json")


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- The data-driven contract -----------------------------------------------


def test_constants_tables_cover_every_type_and_pin_the_magnitudes():
    """Every type has a duration (the table is the idle-economy seam, so an
    unknown type would silently grant no timer), and the magnitudes the
    follow-on economy layer will multiply are pinned."""
    assert POWERUP_DROP_CHANCE == pytest.approx(0.15)
    assert POWERUP_RAPID_COOLDOWN_MULT == pytest.approx(0.4)
    assert POWERUP_TRIPLE_SPREAD == pytest.approx(20.0)
    assert POWERUP_SHIELD_HITS == 1
    for kind in PowerUpType:
        assert kind in POWERUP_DURATION_S
        assert POWERUP_DURATION_S[kind] == pytest.approx(8.0)


# --- Drop rolls (pure, seeded-RNG testable) ---------------------------------


def test_drop_chance_boundary():
    """0.14 drops, 0.16 doesn't; the boundary roll itself doesn't (strict <);
    small rocks never drop whatever the roll."""
    medium, large = ASTEROID_MIN_RADIUS * 2, ASTEROID_MIN_RADIUS * 3
    assert drops_powerup(medium, 0.14)
    assert drops_powerup(large, 0.0)
    assert not drops_powerup(medium, 0.16)
    assert not drops_powerup(medium, POWERUP_DROP_CHANCE)
    assert not drops_powerup(ASTEROID_MIN_RADIUS, 0.0)


def test_pick_type_covers_all_types_under_a_seeded_stream():
    """Type selection is pure in the roll: a seeded random stream maps onto
    all four types and every roll lands on a real one. MAGNET appends at
    the pool's end, so the original three keep their roll bands."""
    random.seed(1234)
    rolls = [random.random() for _ in range(300)]
    assert {pick_type(roll) for roll in rolls} == set(PowerUpType)
    assert pick_type(0.0) is PowerUpType.SHIELD
    assert pick_type(0.749) is PowerUpType.TRIPLE  # the old bands held...
    assert pick_type(0.75) is PowerUpType.MAGNET   # ...the fourth is appended
    assert pick_type(0.999) is PowerUpType.MAGNET
    assert pick_type(1.0) is PowerUpType.MAGNET  # clamped, never IndexError


# --- Effects: apply, expire, magnitudes -------------------------------------


def test_rapid_applies_then_expires_exactly_at_duration():
    pygame.init()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)

    player.activate_powerup(PowerUpType.RAPID)
    assert player.has_rapid

    player.update(POWERUP_DURATION_S["rapid"] / 2)
    assert player.has_rapid
    player.update(POWERUP_DURATION_S["rapid"] / 2)  # the full duration spent
    assert not player.has_rapid


def test_rapid_cooldown_honors_the_multiplier_constant():
    pygame.init()
    _, _, _, shots, _ = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)

    player.shoot()
    assert player.shot_cooldown_timer == pytest.approx(PLAYER_SHOOT_COOLDOWN_SECONDS)

    player.shot_cooldown_timer = 0.0
    player.activate_powerup(PowerUpType.RAPID)
    player.shoot()
    assert player.shot_cooldown_timer == pytest.approx(
        PLAYER_SHOOT_COOLDOWN_SECONDS * POWERUP_RAPID_COOLDOWN_MULT
    )


def test_triple_fires_three_shots_at_the_spread():
    pygame.init()
    _, _, _, shots, _ = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.activate_powerup(PowerUpType.TRIPLE)

    player.shoot()

    assert len(shots) == 3
    # rotation 0 faces (0, 1): the three velocities sit at -spread, 0, +spread
    facing = pygame.Vector2(0, 1)
    spreads = sorted(round(facing.angle_to(shot.velocity)) for shot in shots)
    spread = int(POWERUP_TRIPLE_SPREAD)
    assert spreads == [-spread, 0, spread]


def test_plain_shoot_still_fires_one_centered_shot():
    pygame.init()
    _, _, _, shots, _ = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)

    player.shoot()

    assert len(shots) == 1


def test_shield_expires_unspent_and_then_absorbs_nothing():
    pygame.init()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)

    player.activate_powerup(PowerUpType.SHIELD)
    assert player.shielded
    player.update(POWERUP_DURATION_S["shield"])
    assert not player.shielded

    assert player.absorb_hit() is False  # an expired shield is no shield


# --- Shield through the real hit path ----------------------------------------


def test_shield_absorbs_exactly_one_hit_then_a_hit_costs_a_life(tmp_path):
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.SHIELD)
    Asteroid(100, 660, 40)  # overlapping the ship

    handle_collisions(asteroids, shots, player, game, powerups)

    # absorbed: no life lost, no respawn, the charge is spent, rock alive
    assert game.lives == 3
    assert game.state == "playing"
    assert player.position == pygame.Vector2(100, 660)
    assert player.velocity == pygame.Vector2(0, 0)
    assert not player.shielded
    assert len(asteroids) == 1

    # the same rock, shield gone: a real hit now
    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.lives == 2
    assert player.invulnerable  # respawn granted, as for any hit


def test_shield_restock_picks_the_ring_back_up():
    pygame.init()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.activate_powerup(PowerUpType.SHIELD)
    assert player.absorb_hit() is True

    player.activate_powerup(PowerUpType.SHIELD)  # a fresh drop re-stocks
    assert player.shield_hits == POWERUP_SHIELD_HITS
    assert player.shielded


# --- Collection through the sweep --------------------------------------------


def test_pickup_collects_on_overlap_applies_effect_and_logs(tmp_path):
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    PowerUp(100, 660, PowerUpType.RAPID)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 0
    assert player.has_rapid
    collected = [e for e in read_events(tmp_path) if e["type"] == "powerup_collected"]
    assert len(collected) == 1
    # The detail key is powerup_type: `type=` would collide with the logger's
    # reserved event-type field and erase the discriminator from the log.
    assert collected[0]["powerup_type"] == "rapid"


def test_pickups_do_not_collect_after_game_over(tmp_path):
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    game.lives = 0
    game.state = "game_over"
    PowerUp(100, 660, PowerUpType.RAPID)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 1  # stays put; a dead run grants nothing
    assert not player.has_rapid


# --- Drops through the sweep (deterministic via the patched roll) ------------


def test_destroyed_medium_rock_spawns_a_pickup_at_the_death_site(tmp_path, monkeypatch):
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)  # far from the fight: no player hit
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 2)  # medium: eligible
    Shot(640, 360)
    # two rolls in the sweep: 0.0 drops the pickup, 0.3 picks the second type
    # (RAPID) out of the four-way pool — 0.5 now lands in MAGNET's band
    rolls = iter([0.0, 0.3])
    monkeypatch.setattr(random, "random", lambda: next(rolls))

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 1
    pickup = next(iter(powerups))
    assert pickup.kind is PowerUpType.RAPID
    assert pickup.position == pygame.Vector2(640, 360)
    spawned = [e for e in read_events(tmp_path) if e["type"] == "powerup_spawned"]
    assert len(spawned) == 1
    assert spawned[0]["powerup_type"] == "rapid"


def test_destroyed_small_rock_never_spawns_a_pickup(tmp_path, monkeypatch):
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    Asteroid(640, 360, ASTEROID_MIN_RADIUS)  # small: never eligible
    Shot(640, 360)
    monkeypatch.setattr(random, "random", lambda: 0.0)  # a winning roll, wasted

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 0
    assert sum(e["type"] == "powerup_spawned" for e in read_events(tmp_path)) == 0


def test_losing_the_roll_spawns_nothing(tmp_path, monkeypatch):
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 3)  # large: eligible, unlucky
    Shot(640, 360)
    monkeypatch.setattr(random, "random", lambda: 0.99)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 0
    assert sum(e["type"] == "powerup_spawned" for e in read_events(tmp_path)) == 0


# --- World hygiene -----------------------------------------------------------


def test_pickup_drifts_then_despawns_fully_off_screen():
    pygame.init()
    _, _, _, _, powerups = make_groups()
    pickup = PowerUp(200, 360, PowerUpType.TRIPLE)
    pickup.velocity = pygame.Vector2(-30, 0)  # test-controlled drift

    pickup.update(1.0)  # 30px left, still on screen
    assert pickup.alive()

    pickup.position.x = -POWERUP_RADIUS - 1  # fully past the left edge
    pickup.update(0.016)
    assert not pickup.alive()


def test_restart_clears_pickups_and_active_effects(tmp_path):
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    PowerUp(200, 200, PowerUpType.TRIPLE)
    player.activate_powerup(PowerUpType.RAPID)
    player.activate_powerup(PowerUpType.SHIELD)
    assert len(powerups) == 1 and player.has_rapid and player.shielded

    game.restart()

    # a stale pickup or lingering buff in a fresh run would be a visible lie
    assert len(powerups) == 0
    assert not player.has_rapid
    assert not player.shielded
    assert player.powerup_timers == {}


# --- Rendering (headless pixels) ---------------------------------------------


def test_pickup_renders_its_letter_inside_the_circle():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pickup = PowerUp(640, 360, PowerUpType.SHIELD)

    screen.fill(PALETTE["paper"])
    pickup.draw(screen)

    # the letter is stamped mid-circle (the outline at r=14 is outside the box)
    box = [
        screen.get_at((640 + dx, 360 + dy))
        for dx in range(-8, 9, 2)
        for dy in range(-8, 9, 2)
    ]
    assert any(pixel != (*PALETTE["paper"], 255) for pixel in box)


def test_shield_ring_draws_outside_the_hull_only_while_stocked():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    ring = PLAYER_RADIUS + POWERUP_SHIELD_RING_GAP
    ring_y = int(SCREEN_HEIGHT / 2)
    # pygame outlines cover [r - width, r), so sample the stroke's band
    band = range(int(SCREEN_WIDTH / 2) + ring - 3, int(SCREEN_WIDTH / 2) + ring + 4)

    screen.fill(PALETTE["paper"])
    player.draw(screen)
    assert all(
        screen.get_at((x, ring_y)) == (*PALETTE["paper"], 255) for x in band
    )  # no ring

    player.activate_powerup(PowerUpType.SHIELD)
    screen.fill(PALETTE["paper"])
    player.draw(screen)
    assert any(
        screen.get_at((x, ring_y)) != (*PALETTE["paper"], 255) for x in band
    )  # ring on
