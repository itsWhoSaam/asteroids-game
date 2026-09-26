"""Impulse collision response (physics overhaul): the pure contact helper
and its two integration points in the sweep.

resolve_contact is separable from the rules by construction — velocities
and positions in, velocities and positions out, never an event — so the
pure tests pin the conservation math on constructed bodies, and the
integration tests pin the sweep's guarantees: a rock↔rock bounce is free
(no kills, no mints, no events, no despawned flips), a hit shoves both
bodies before the untouched player_hit flow, the boss is a wall, chrono
slows the momentum and not the bounce, and frozen frames resolve nothing.
"""

import json
import math

import pygame
import pytest

from asteroid import Asteroid, Boss
from circleshape import CircleShape, resolve_contact
from constants import (
    ASTEROID_MIN_RADIUS,
    COLLISION_RESTITUTION,
    PLAYER_MASS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from main import destroyed_asteroids, handle_collisions, mint_destructions
from player import Player
from powerups import PowerUp
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
    return Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def body(x, y, radius, velocity=(0.0, 0.0)):
    """A bare unit-mass circle at a spot, for the pure contact math."""
    b = CircleShape(x, y, radius)
    b.velocity = pygame.Vector2(velocity)
    return b


def pair_momentum(bodies):
    """Vector sum of momentum: velocity over inverse mass. Returns plain
    components — pytest.approx's element-wise comparison against pygame
    Vector2 misreports matched pairs, so the tests compare tuples."""
    total = sum(
        (b.velocity / b.inverse_mass for b in bodies),
        pygame.Vector2(0, 0),
    )
    return (total.x, total.y)


def pair_kinetic_energy(bodies):
    """Total kinetic energy: ½·m·v² with m = 1 / inverse_mass."""
    return sum(
        0.5 * b.velocity.length_squared() / b.inverse_mass for b in bodies
    )


@pytest.fixture(autouse=True)
def chrono_scale_restored():
    """The chrono scale is class-level state the sweep publishes every
    frame — every test leaves the baseline restored exactly."""
    yield
    Asteroid.speed_scale = 1.0


# --- pure contact math --------------------------------------------------------


def test_equal_mass_head_on_exchanges_velocities_scaled_by_restitution():
    """The anchor case: two equal masses meeting head-on rebound with
    velocities exchanged and scaled by e — the elastic exchange, damped
    by the restitution."""
    a = body(0, 0, 20, (100, 0))
    b = body(39, 0, 20, (-100, 0))  # 1 px overlap, closing at 200 px/s

    impulse = resolve_contact(a, b)

    e = COLLISION_RESTITUTION
    assert impulse == pytest.approx((1 + e) * 200 / 2)
    assert a.velocity.x == pytest.approx(-e * 100)
    assert b.velocity.x == pytest.approx(e * 100)
    assert a.velocity.y == 0.0
    assert b.velocity.y == 0.0


def test_contact_conserves_momentum_along_the_normal():
    """Impulse-only response: the pair's momentum sum is invariant, and
    the component perpendicular to the normal passes through untouched."""
    a = body(0, 0, 20, (90, 30))
    b = body(35, 0, 20, (-60, -10))
    momentum_before = pair_momentum([a, b])

    resolve_contact(a, b)

    assert pair_momentum([a, b]) == pytest.approx(momentum_before)
    assert a.velocity.y == pytest.approx(30.0)  # tangential, untouched
    assert b.velocity.y == pytest.approx(-10.0)


def test_head_on_kinetic_loss_matches_the_restitution_share():
    """A head-on pair's energy loss is exactly the (1 - e²) share —
    restitution below 1 is what lets piles settle instead of ringing."""
    a = body(0, 0, 20, (100, 0))
    b = body(39, 0, 20, (-100, 0))
    ke_before = pair_kinetic_energy([a, b])

    resolve_contact(a, b)

    e = COLLISION_RESTITUTION
    assert ke_before - pair_kinetic_energy([a, b]) == pytest.approx(
        (1 - e**2) * ke_before
    )


def test_unequal_masses_shift_the_lighter_rock_more():
    """Mass-proportional response: the light rock's velocity swings nine
    times as far as the large rock's, the pair still conserves momentum,
    and the energy loss is the exact (1 - e²)·μ·closing² share of the
    closing speed (μ the reduced mass)."""
    light = Asteroid(0, 0, ASTEROID_MIN_RADIUS)       # mass 1
    heavy = Asteroid(79, 0, ASTEROID_MIN_RADIUS * 3)  # mass 9, 1 px overlap
    heavy.velocity = pygame.Vector2(-50, 0)
    heavy_before = heavy.velocity.copy()
    momentum_before = pair_momentum([light, heavy])
    ke_before = pair_kinetic_energy([light, heavy])
    closing = 50.0
    reduced_mass = 1.0 / (light.inverse_mass + heavy.inverse_mass)

    resolve_contact(light, heavy)

    light_shift = light.velocity.length()
    heavy_shift = (heavy.velocity - heavy_before).length()
    assert light_shift > heavy_shift
    assert light_shift / heavy_shift == pytest.approx(
        light.inverse_mass / heavy.inverse_mass
    )
    assert pair_momentum([light, heavy]) == pytest.approx(momentum_before)
    e = COLLISION_RESTITUTION
    expected_loss = (1 - e**2) * reduced_mass * closing**2 / 2
    assert ke_before - pair_kinetic_energy([light, heavy]) == pytest.approx(
        expected_loss
    )


def test_depenetration_separates_the_pair_without_residual_overlap():
    """Full-overlap positional correction split by inverse mass: after
    the contact the hulls touch exactly but no longer overlap."""
    a = body(0, 0, 20)
    b = body(30, 0, 20)  # 10 px overlap, both at rest

    result = resolve_contact(a, b)

    assert result == 0.0  # no closing speed: de-penetration only
    assert a.position.x == pytest.approx(-5.0)
    assert b.position.x == pytest.approx(35.0)
    assert a.position.distance_to(b.position) >= 40 - 1e-6


def test_separating_contact_adds_no_impulse():
    """Bodies already flying apart get only the positional separation —
    no impulse may add speed to a separating contact."""
    a = body(0, 0, 20, (-100, 0))
    b = body(30, 0, 20, (100, 0))  # overlapping, separating at 200 px/s

    result = resolve_contact(a, b)

    assert result == 0.0
    assert a.velocity == pygame.Vector2(-100, 0)
    assert b.velocity == pygame.Vector2(100, 0)
    assert a.position.distance_to(b.position) >= 40 - 1e-6


def test_not_touching_returns_none_and_changes_nothing():
    a = body(0, 0, 20, (100, 0))
    b = body(61, 0, 20, (-100, 0))  # 1 px clear of contact

    assert resolve_contact(a, b) is None
    assert a.position == pygame.Vector2(0, 0)
    assert b.position == pygame.Vector2(61, 0)
    assert a.velocity == pygame.Vector2(100, 0)
    assert b.velocity == pygame.Vector2(-100, 0)


# --- body model ---------------------------------------------------------------


def test_asteroid_mass_scales_with_the_radius_ratio_squared():
    assert Asteroid(0, 0, ASTEROID_MIN_RADIUS).inverse_mass == pytest.approx(1.0)
    assert Asteroid(
        0, 0, ASTEROID_MIN_RADIUS * 2
    ).inverse_mass == pytest.approx(0.25)
    assert Asteroid(
        0, 0, ASTEROID_MIN_RADIUS * 3
    ).inverse_mass == pytest.approx(1 / 9)


def test_boss_is_infinitely_massive():
    assert Boss(100, 100, 1).inverse_mass == 0.0


def test_ship_is_a_fixed_small_body():
    assert Player(100, 100).inverse_mass == pytest.approx(1.0 / PLAYER_MASS)


def test_two_immovable_bodies_cannot_respond():
    """Two infinite-mass bodies have no impulse to exchange — the guard
    keeps a boss pile from dividing by zero."""
    a = Boss(100, 100, 1)
    b = Boss(200, 100, 1)  # hulls of 80 overlap by 60

    assert resolve_contact(a, b) is None
    assert a.position == pygame.Vector2(100, 100)
    assert b.position == pygame.Vector2(200, 100)


def test_boss_wall_reflects_the_ship_and_never_moves():
    ship = Player(300, 300)
    ship.velocity = pygame.Vector2(150, 0)
    boss = Boss(320, 300, 1)  # hull radius 80: ship deep inside

    impulse = resolve_contact(ship, boss)

    assert impulse > 0
    assert boss.velocity == pygame.Vector2(0, 0)
    assert boss.position == pygame.Vector2(320, 300)
    assert ship.velocity.x < 0  # reflected off the hull
    assert ship.position.distance_to(boss.position) >= 100 - 1e-6


# --- sweep integration --------------------------------------------------------


def test_rock_rock_bounce_is_free(tmp_path):
    """A bounce removes no sprite, flips no despawned flag, emits no
    event, and pays nothing: the destruction diff and the mint poll both
    come away empty (spec criterion 4)."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    economy = Economy(save_path=tmp_path / "economy_save.json")
    rock_a = Asteroid(100, 100, ASTEROID_MIN_RADIUS)
    rock_a.velocity = pygame.Vector2(80, 0)
    rock_b = Asteroid(139, 100, ASTEROID_MIN_RADIUS)
    rock_b.velocity = pygame.Vector2(-80, 0)
    previous = set(asteroids)

    handle_collisions(asteroids, shots, player, game, powerups, dt=1 / 60)

    assert len(asteroids) == 2
    assert rock_a.alive() and rock_b.alive()
    assert not rock_a.despawned and not rock_b.despawned
    assert rock_a.velocity.x < 0 and rock_b.velocity.x > 0  # they bounced
    assert destroyed_asteroids(previous, asteroids) == []
    assert mint_destructions(previous, asteroids, economy, game.stats) == []
    assert economy.credits == 0.0
    events = read_events(tmp_path)
    assert not any(
        event["type"] in ("asteroid_split", "credit_minted", "player_hit")
        for event in events
    )


def test_sweep_bounces_the_field_off_an_unmoved_boss(tmp_path):
    """The boss is a wall in the pair pass too: the ship's contact still
    flows through the untouched rules — exactly one player_hit, one life —
    while the boss's position and velocity never move (spec criterion 6)."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(300, 300)
    player.velocity = pygame.Vector2(150, 0)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    boss = Boss(320, 300, 1)

    handle_collisions(asteroids, shots, player, game, powerups, dt=1 / 60)

    assert boss.position == pygame.Vector2(320, 300)
    assert boss.velocity == pygame.Vector2(0, 0)
    assert boss.alive()
    assert sum(
        event["type"] == "player_hit" for event in read_events(tmp_path)
    ) == 1
    assert game.lives == 2  # the rules priced the hit exactly once
    assert player.position == pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)


def test_shielded_hit_shoves_both_bodies_before_the_rules(tmp_path):
    """Physics accompanies the rules (spec criterion 5): a shielded hit
    never respawns, so the shove stays visible — both bodies carry the
    impulse, the charge is spent, and no life is lost."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    player.grant_shield(1)
    player.velocity = pygame.Vector2(30, 0)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    rock = Asteroid(135, 660, ASTEROID_MIN_RADIUS)
    rock.velocity = pygame.Vector2(-60, 0)

    handle_collisions(asteroids, shots, player, game, powerups, dt=1 / 60)

    assert game.lives == 3  # the shield ate the hit
    assert player.shield_hits == 0
    assert sum(
        event["type"] == "player_hit" for event in read_events(tmp_path)
    ) == 1
    assert player.position != pygame.Vector2(
        SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2
    )  # no respawn — the shove stayed on the field
    assert player.velocity.x < 0  # shoved back off the rock
    assert rock.velocity.x > 0  # shoved away from the ship
    assert player.position.distance_to(rock.position) >= 40 - 1e-6


def test_chrono_slowed_rocks_exchange_momentum_by_effective_velocity():
    """Half-speed rocks (speed_scale 0.5) close at half the rate, so the
    exchanged impulse halves with them — slow motion feels heavy, not
    floaty (spec criterion 10)."""
    def head_on_impulse(scale):
        Asteroid.speed_scale = scale
        a = Asteroid(0, 0, ASTEROID_MIN_RADIUS)
        b = Asteroid(39, 0, ASTEROID_MIN_RADIUS)
        a.velocity = pygame.Vector2(100, 0)
        b.velocity = pygame.Vector2(-100, 0)
        return resolve_contact(a, b)

    full = head_on_impulse(1.0)
    slowed = head_on_impulse(0.5)

    assert slowed == pytest.approx(full * 0.5)
    Asteroid.speed_scale = 1.0  # restores exactly (the fixture guards too)


def test_chrono_pair_bounces_through_the_sweep(tmp_path):
    """The same composition through handle_collisions: the pair pass
    reads effective velocities, the bounce stays free, and the exact
    restore contract holds once the scale returns to 1.0."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    rock_a = Asteroid(100, 100, ASTEROID_MIN_RADIUS)
    rock_a.velocity = pygame.Vector2(100, 0)
    rock_b = Asteroid(139, 100, ASTEROID_MIN_RADIUS)
    rock_b.velocity = pygame.Vector2(-100, 0)
    Asteroid.speed_scale = 0.5

    handle_collisions(asteroids, shots, player, game, powerups, dt=1 / 60)

    e = COLLISION_RESTITUTION
    expected = (1 + e) * 100 / 2  # closing 100 at half speed, two unit masses
    assert rock_a.velocity.x == pytest.approx(100 - expected)
    assert rock_b.velocity.x == pytest.approx(-100 + expected)
    assert len(asteroids) == 2  # a slowed bounce is still free
    Asteroid.speed_scale = 1.0


def test_many_rock_pile_up_stays_stable(tmp_path):
    """Twelve large rocks overlapping in a dense grid, sixty resolved
    frames: nobody dies, every velocity stays finite, the books never
    move, and the pile's kinetic energy only ever dissipates —
    restitution < 1 plus inverse-mass de-penetration settles a pile,
    never explodes it (the pile-up-jitter risk)."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    rocks = []
    for row in range(3):
        for col in range(4):
            rock = Asteroid(
                150 + col * 90, 120 + row * 90, ASTEROID_MIN_RADIUS * 3
            )
            rock.velocity = pygame.Vector2(
                40.0 * ((col % 3) - 1), 30.0 * ((row % 3) - 1)
            )
            rocks.append(rock)
    previous = set(asteroids)
    ke_start = pair_kinetic_energy(rocks)

    dt = 1 / 60
    for _ in range(60):
        handle_collisions(asteroids, shots, player, game, powerups, dt=dt)
        for rock in rocks:
            rock.position += rock.velocity * dt  # the frame's integration

    assert len(asteroids) == 12
    assert all(rock.alive() and not rock.despawned for rock in rocks)
    assert all(
        math.isfinite(rock.velocity.x) and math.isfinite(rock.velocity.y)
        for rock in rocks
    )
    assert pair_kinetic_energy(rocks) <= ke_start + 1e-6
    assert destroyed_asteroids(previous, asteroids) == []
    events = read_events(tmp_path)
    assert not any(
        event["type"] in ("asteroid_split", "credit_minted", "player_hit")
        for event in events
    )


def test_frozen_frame_resolves_no_contacts(tmp_path):
    """dt = 0 (hit-stop, pause) applies no impulse and no de-penetration:
    an overlapping pair's positions and velocities survive the frozen
    sweep untouched (spec criterion 7)."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    rock_a = Asteroid(100, 100, ASTEROID_MIN_RADIUS)
    rock_a.velocity = pygame.Vector2(80, 0)
    rock_b = Asteroid(139, 100, ASTEROID_MIN_RADIUS)
    rock_b.velocity = pygame.Vector2(-80, 0)

    handle_collisions(asteroids, shots, player, game, powerups, dt=0)

    assert rock_a.position == pygame.Vector2(100, 100)
    assert rock_b.position == pygame.Vector2(139, 100)
    assert rock_a.velocity == pygame.Vector2(80, 0)
    assert rock_b.velocity == pygame.Vector2(-80, 0)
    assert len(asteroids) == 2


def test_frozen_frame_shoves_nothing_but_rules_still_resolve(tmp_path):
    """A frozen frame's ship contact prices the hit — the rules hook is
    where it always was — but applies no impulse: the rock's velocity is
    untouched (spec criterion 7's impulse clause)."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    rock = Asteroid(140, 660, ASTEROID_MIN_RADIUS)  # touching the hull
    rock.velocity = pygame.Vector2(-60, 0)

    handle_collisions(asteroids, shots, player, game, powerups, dt=0)

    assert rock.velocity == pygame.Vector2(-60, 0)  # no impulse applied
    assert sum(
        event["type"] == "player_hit" for event in read_events(tmp_path)
    ) == 1
    assert game.lives == 2
