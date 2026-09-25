"""Tests for the UFO saucer (Tier 3): spawn cadence, sinusoidal drift, aimed
fire, and the sweep integration — saucer shots split rocks and reach the ship,
the saucer dies to one shot for its own points tier.

The saucer reuses every existing seam, so these tests mirror the neighbors':
spawn cadence follows the drone-turret tests' overshoot-carries pattern, the
integration cases follow test_handle_collisions' group harness, and the mint
checks ride the destroyed_ufos frame diff — the rocks' one destruction→mint
path with a saucer-shaped input.
"""

import json
import random as random_module

import pygame
import pytest

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import (
    ASTEROID_MIN_RADIUS,
    SCORE_LARGE,
    SCORE_MEDIUM,
    SCORE_SMALL,
    SCORE_UFO,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    UFO_EDGE_MARGIN,
    UFO_FIRE_INTERVAL_S,
    UFO_RADIUS,
    UFO_SHOT_SPEED,
    UFO_SPAWN_INTERVAL_S,
    UFO_SPEED,
    UFO_WOBBLE_AMPLITUDE,
)
from drones import DroneBay
from economy import Economy
from game import Game
from hud import WaveBanner, points_for
from main import (
    FloatingText,
    destroyed_asteroids,
    handle_collisions,
    restart_run,
    select_mode,
    update_world,
)
from particles import Particle, Shake
from player import Player
from powerups import PowerUp
from shot import Shot
from ufo import UFO, UFOSpawner, aim_vector, destroyed_ufos, ufo_spawn_plan


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    ufos = pygame.sprite.Group()
    floaters = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    AsteroidField.containers = (updatable,)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    UFO.containers = (ufos, updatable, drawable)
    FloatingText.containers = (floaters, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)

    return updatable, drawable, asteroids, shots, ufos, floaters, powerups


def make_game(tmp_path, player, asteroids, shots, ufos=None):
    """A Game wired to the given world, saving into tmp_path."""
    return Game(player, asteroids, shots,
                save_path=tmp_path / "game_save.json", ufos=ufos)


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def place_saucer(ufo, x, y, heading=(UFO_SPEED, 0)):
    """Put a saucer at a known spot: the entry plan is random, so the tests
    pin the crossing afterwards — the position re-derives from base_position
    on update, so a zero-dt update snaps it onto the new baseline."""
    ufo.base_position = pygame.Vector2(x, y)
    ufo.velocity = pygame.Vector2(heading)
    ufo.wobble_axis = ufo.velocity.rotate(90).normalize()
    ufo.update(0.0)
    return ufo


# --- spawn cadence ----------------------------------------------------------


def test_spawner_fires_on_the_interval():
    """Nothing spawns before the full interval; one saucer exists at it."""
    _updatable, _drawable, _asteroids, _shots, ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    spawner = UFOSpawner()

    spawner.update(UFO_SPAWN_INTERVAL_S - 0.05, player)
    assert len(ufos) == 0

    spawner.update(0.1, player)  # crosses the boundary: -0.05 in the hole
    assert len(ufos) == 1


def test_spawner_cadence_is_a_true_interval():
    """After the first entry the next waits a full interval — overshoot
    carries, so the cadence stays a true 45 s, not 'up to 45 s'."""
    _updatable, _drawable, _asteroids, _shots, ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    spawner = UFOSpawner()

    spawner.update(UFO_SPAWN_INTERVAL_S, player)  # fires
    assert len(ufos) == 1

    spawner.update(UFO_SPAWN_INTERVAL_S - 0.05, player)
    assert len(ufos) == 1

    spawner.update(0.1, player)  # cumulative 2 × interval → fires
    assert len(ufos) == 2


def test_spawned_ufo_enters_from_an_edge():
    """A fresh saucer starts off-screen, aims inward, and is not a cull."""
    _updatable, _drawable, _asteroids, _shots, _ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    ufo = UFOSpawner().spawn(player)

    pos = ufo.position
    off_screen = (
        pos.x < 0 or pos.x > SCREEN_WIDTH or pos.y < 0 or pos.y > SCREEN_HEIGHT
    )
    assert off_screen
    center = pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    assert ufo.velocity.dot(center - pos) > 0  # heading toward the play field
    assert not ufo.despawned


def test_ufo_spawn_event_logged(tmp_path):
    """The saucer's entry logs ufo_spawned with its edge, per the
    powerup_spawned precedent."""
    _updatable, _drawable, _asteroids, _shots, _ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    spawner = UFOSpawner()
    spawner.update(UFO_SPAWN_INTERVAL_S, player)

    events = [e for e in read_events(tmp_path) if e["type"] == "ufo_spawned"]
    assert len(events) == 1
    assert events[0]["edge"] in (0, 1, 2, 3)


def test_spawn_plan_is_seedable_deterministic():
    """The plan is pure: the same seeded rng yields the same entry."""
    _updatable, _drawable, _asteroids, _shots, _ufos, _floaters, _powerups = make_groups()

    first = ufo_spawn_plan(random_module.Random(1234))
    second = ufo_spawn_plan(random_module.Random(1234))
    assert first == second


def test_ufo_despawns_past_the_cull_margin():
    """A crossing that exits the far edge is flagged and killed — the cull
    the mint diff must skip; a mid-screen saucer survives its update."""
    _updatable, _drawable, _asteroids, _shots, _ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)

    crossed = UFO(player)
    crossed.base_position = pygame.Vector2(
        SCREEN_WIDTH + UFO_EDGE_MARGIN + 50, SCREEN_HEIGHT / 2
    )
    crossed.update(1 / 60)
    assert crossed.despawned
    assert not crossed.alive()

    flying = UFO(player)
    place_saucer(flying, SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    flying.update(1 / 60)
    assert not flying.despawned
    assert flying.alive()


def test_destroyed_ufos_pays_kills_not_culls():
    """The saucer frame diff mirrors destroyed_asteroids: a shot-down saucer
    surfaces; one that crossed and exited never does."""
    _updatable, _drawable, _asteroids, _shots, _ufos, _floaters, _powerups = make_groups()
    shot_down = UFO()
    crossed_out = UFO()
    crossed_out.despawned = True

    # Neither is in the current frame's group: only the un-flagged one pays.
    assert destroyed_ufos([shot_down, crossed_out], []) == [shot_down]
    # Both still present: nothing pays.
    assert destroyed_ufos([shot_down, crossed_out], [shot_down, crossed_out]) == []


def test_ufo_drifts_sinusoidally():
    """The position swings perpendicular to travel, peaking at ±amplitude,
    while the crossing itself advances monotonically."""
    _updatable, _drawable, _asteroids, _shots, _ufos, _floaters, _powerups = make_groups()
    ufo = UFO()
    place_saucer(ufo, 300, SCREEN_HEIGHT / 2)

    offsets = []
    xs = []
    for _ in range(240):  # two full sine periods at UFO_WOBBLE_HZ = 0.5
        ufo.update(1 / 120)
        offsets.append(ufo.position.y - ufo.base_position.y)
        xs.append(ufo.position.x)

    assert max(offsets) == pytest.approx(UFO_WOBBLE_AMPLITUDE, abs=1.0)
    assert min(offsets) == pytest.approx(-UFO_WOBBLE_AMPLITUDE, abs=1.0)
    assert xs == sorted(xs)  # the crossing never walks backward


# --- fire aim ---------------------------------------------------------------


def test_aim_vector_points_at_the_target():
    """Pure aim: a unit vector toward the target; a zero-length aim fires
    along +x rather than dividing by zero."""
    aim = aim_vector(pygame.Vector2(0, 0), pygame.Vector2(3, 4))
    assert aim.x == pytest.approx(0.6)
    assert aim.y == pytest.approx(0.8)

    degenerate = aim_vector(pygame.Vector2(5, 5), pygame.Vector2(5, 5))
    assert degenerate.x == pytest.approx(1)
    assert degenerate.y == pytest.approx(0)


def test_ufo_fire_sends_an_aimed_shot():
    """Firing puts one real Shot in the shared group, tagged from_ufo,
    flying toward the target at the saucer's shot speed — and the muzzle
    starts outside the hull, so the fresh bullet cannot self-collide."""
    _updatable, _drawable, _asteroids, shots, _ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH - 100, SCREEN_HEIGHT / 2)
    ufo = UFO(player)
    place_saucer(ufo, 100, SCREEN_HEIGHT / 2)

    shot = ufo.fire(player.position)

    assert len(shots) == 1  # joined the shared group via Shot.containers
    assert shot.from_ufo
    assert not shot.from_drone
    assert shot.velocity.length() == pytest.approx(UFO_SHOT_SPEED)
    # Aimed at the player: same direction as saucer→player.
    to_player = player.position - ufo.position
    assert shot.velocity.dot(to_player) > 0
    # The muzzle started outside the hull — no instant self-kill in the sweep.
    assert shot.position.distance_to(ufo.position) > UFO_RADIUS + shot.radius


def test_ufo_fire_cadence_is_a_true_interval():
    """The saucer's fire clock: a full interval between shots, exact-reset
    (not the turret's overshoot carry) — the cadence cannot depend on where
    a fractional frame lands the clock."""
    _updatable, _drawable, _asteroids, shots, _ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    ufo = UFO(player)
    place_saucer(ufo, 100, 100)

    ufo.update(UFO_FIRE_INTERVAL_S - 0.05)
    assert len(shots) == 0
    ufo.update(0.1)  # crosses the boundary: fires
    assert len(shots) == 1

    ufo.update(UFO_FIRE_INTERVAL_S - 0.05)
    assert len(shots) == 1
    ufo.update(0.1)  # fires again
    assert len(shots) == 2


def test_ufo_without_a_player_never_fires():
    """No target injected, no fire — the purity tests' mode of use."""
    _updatable, _drawable, _asteroids, shots, _ufos, _floaters, _powerups = make_groups()
    ufo = UFO()
    place_saucer(ufo, 100, 100)

    ufo.update(UFO_FIRE_INTERVAL_S * 3)

    assert len(shots) == 0


# --- collision integration --------------------------------------------------


def frame_step(ufo, game, asteroids, shots, player, powerups, ufos, economy,
               prev_asteroids, prev_ufos):
    """One full game-frame pass: update, sweep, and the two mint polls —
    the same shape as main()'s unpaused block. The callers refresh both
    prev-snapshots after the step. Shots move here (the loop's
    updatable.update step), or a bullet would sit at the muzzle forever."""
    ufo.update(1 / 60)
    for shot in list(shots):
        shot.update(1 / 60)
    handle_collisions(asteroids, shots, player, game, powerups, ufos=ufos)
    for wreck in destroyed_asteroids(prev_asteroids, asteroids):
        economy.mint(wreck.radius)
    for wreck in destroyed_ufos(prev_ufos, ufos):
        economy.mint(wreck.radius)


def test_ufo_shot_splits_asteroid_and_mints(tmp_path):
    """The integration case: a saucer's aimed shot destroys an asteroid —
    the rock pays the ordinary points tier on the score and mints through
    the ordinary diff, and the shot dies in the rock (it cannot fly on to
    the player behind it)."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, ufos, _floaters, powerups = make_groups()
    player = Player(900, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)
    economy = Economy(save_path=str(tmp_path / "game_save.json"))

    ufo = UFO(player)
    place_saucer(ufo, 200, SCREEN_HEIGHT / 2)
    ufo.fire_timer = 0.0  # fire on the very next frame
    Asteroid(400, SCREEN_HEIGHT / 2, ASTEROID_MIN_RADIUS)

    prev_asteroids = set(asteroids)
    prev_ufos = set(ufos)
    for _ in range(120):
        frame_step(ufo, game, asteroids, shots, player, powerups, ufos,
                   economy, prev_asteroids, prev_ufos)
        prev_asteroids = set(asteroids)
        prev_ufos = set(ufos)
        if len(asteroids) == 0:
            break

    assert len(asteroids) == 0  # the saucer's shot split the rock
    assert game.score == SCORE_SMALL
    assert economy.credits == pytest.approx(SCORE_SMALL)
    assert game.lives == 3  # the shot died in the rock; the ship is safe


def test_ufo_shot_hits_player_through_player_hit(tmp_path):
    """The saucer's aimed shot is the only shot that reaches the ship: the
    hit routes through the one player-hit flow — a life lost, respawn at
    center, player_hit logged."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, ufos, _floaters, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, 500)
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)

    ufo = UFO(player)
    place_saucer(ufo, SCREEN_WIDTH / 2, 200, heading=(0, UFO_SPEED))
    ufo.fire_timer = 0.0

    for _ in range(120):
        ufo.update(1 / 60)
        for shot in list(shots):
            shot.update(1 / 60)
        handle_collisions(asteroids, shots, player, game, powerups, ufos=ufos)
        if game.lives == 2:
            break

    assert game.lives == 2
    assert player.position == pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    assert player.invulnerable
    assert sum(e["type"] == "player_hit" for e in read_events(tmp_path)) >= 1


def test_ufo_shot_respects_invulnerability(tmp_path):
    """A respawning ship inside the grace window ignores the saucer's shot —
    the same gate the asteroid hit branch applies."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, ufos, _floaters, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.invulnerability_timer = 1.0  # inside the grace window
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)

    ufo = UFO(player)
    place_saucer(ufo, SCREEN_WIDTH / 2 - 200, SCREEN_HEIGHT / 2)
    shot = ufo.fire(player.position)
    shot.position = player.position  # dead overlap: would hit without the gate

    handle_collisions(asteroids, shots, player, game, powerups, ufos=ufos)

    assert game.lives == 3


def test_player_shot_destroys_the_ufo_and_pays_points(tmp_path):
    """One player shot kills the saucer: its own points_for tier lands on
    the score, the white points popup floats, and the mint pays the same
    tier through the destroyed_ufos diff — never for a cull."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, ufos, floaters, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.invulnerability_timer = 0.0
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)
    economy = Economy(save_path=str(tmp_path / "game_save.json"))

    ufo = UFO(player)
    place_saucer(ufo, 200, SCREEN_HEIGHT / 2)
    Shot(230, SCREEN_HEIGHT / 2).velocity = pygame.Vector2(300, 0)

    prev_ufos = set(ufos)
    handle_collisions(asteroids, shots, player, game, powerups, ufos=ufos)

    assert not ufo.alive()
    assert game.score == SCORE_UFO
    kills = destroyed_ufos(prev_ufos, ufos)
    assert kills == [ufo]
    for wreck in kills:
        economy.mint(wreck.radius)
    assert economy.credits == pytest.approx(SCORE_UFO)
    # The points popup floats at the death site (display only).
    assert len(floaters) == 1


def test_ufo_ram_hits_the_player(tmp_path):
    """The saucer rams like any body: overlap with a live, unshielded ship
    costs a life through player_hit — and the saucer survives the ram."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, ufos, _floaters, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.invulnerability_timer = 0.0
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)

    ufo = UFO(player)
    place_saucer(ufo, SCREEN_WIDTH / 2 + 10, SCREEN_HEIGHT / 2)

    handle_collisions(asteroids, shots, player, game, powerups, ufos=ufos)

    assert game.lives == 2
    assert ufo.alive()  # the ram is not mutual destruction


def test_saucer_shots_stay_out_of_the_accuracy_read(tmp_path):
    """Saucer shots ride the pipeline but never count as the player's hits —
    the accuracy read stays the ship's own (the from_drone precedent)."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, ufos, _floaters, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)

    ufo = UFO(player)
    place_saucer(ufo, 100, 100)
    ufo.fire(player.position)

    assert all(shot.from_ufo and not shot.from_drone for shot in shots)
    handle_collisions(asteroids, shots, player, game, powerups, ufos=ufos)

    assert game.lives == 3  # the shot is still in flight, far from the ship
    assert game.stats.shots_fired == 0
    assert game.stats.shots_hit == 0


# --- points tier ------------------------------------------------------------


def test_points_for_ufo_tier():
    """The saucer's exact radius is its own tier, and the rock bands are
    untouched — the exact match never steals a rock's band."""
    assert points_for(UFO_RADIUS) == SCORE_UFO
    assert points_for(ASTEROID_MIN_RADIUS) == SCORE_SMALL
    assert points_for(ASTEROID_MIN_RADIUS * 2) == SCORE_MEDIUM
    assert points_for(ASTEROID_MIN_RADIUS * 3) == SCORE_LARGE


# --- restart hooks ----------------------------------------------------------


def test_restart_clears_ufos_and_resets_the_clock(tmp_path):
    """Both restart hooks land: Game.restart clears every live saucer (as
    culls — the diff must not mint for them), and restart_run resets the
    saucer clock so a fresh run waits a full interval."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)
    economy = Economy(save_path=str(tmp_path / "game_save.json"))
    field = AsteroidField(game)
    spawner = UFOSpawner()

    ufo = UFO(player)
    place_saucer(ufo, SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    assert len(ufos) == 1

    spawner.update(10.0, player)  # wind the clock into the interval
    prev_ufos = set(ufos)
    restart_run(game, economy, field, WaveBanner(), asteroids, spawner)

    assert len(ufos) == 0  # the saucer died with the run
    assert ufo.despawned  # flagged as a cull: never mints for the restart
    assert destroyed_ufos(prev_ufos, ufos) == []
    assert spawner.timer == UFO_SPAWN_INTERVAL_S
    assert game.wave == 1


def test_restart_resets_the_saucer_clock_through_select_mode(tmp_path):
    """select_mode funnels through restart_run — the clock reset rides it."""
    pygame.init()
    _updatable, _drawable, asteroids, shots, _ufos, _floaters, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots)
    economy = Economy(save_path=str(tmp_path / "game_save.json"))
    field = AsteroidField(game)
    spawner = UFOSpawner()

    spawner.update(10.0, player)
    select_mode(game, economy, field, WaveBanner(), asteroids, "easy", spawner)

    assert spawner.timer == UFO_SPAWN_INTERVAL_S


# --- freeze gating ----------------------------------------------------------


def test_pause_and_menu_freeze_the_saucer_clock(tmp_path):
    """update_world freezes the whole sim while paused or in the menu — the
    saucer clock is a plain object beside the drone bay, so it never ticks
    a frozen frame (the pause flag is the entire gate)."""
    pygame.init()
    updatable, _drawable, asteroids, shots, ufos, _floaters, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, ufos=ufos)
    economy = Economy(save_path=str(tmp_path / "game_save.json"))
    field = AsteroidField(game)
    spawner = UFOSpawner()
    shake = Shake()
    banner = WaveBanner()

    game.paused = True
    update_world(updatable, DroneBay(economy), asteroids, shots, player, game,
                 powerups, shake, field, banner, economy, 1 / 60,
                 ufo_spawner=spawner, ufos=ufos)
    assert spawner.timer == UFO_SPAWN_INTERVAL_S

    game.paused = False
    game.state = "menu"
    update_world(updatable, DroneBay(economy), asteroids, shots, player, game,
                 powerups, shake, field, banner, economy, 1 / 60,
                 ufo_spawner=spawner, ufos=ufos)
    assert spawner.timer == UFO_SPAWN_INTERVAL_S

    game.state = "playing"
    update_world(updatable, DroneBay(economy), asteroids, shots, player, game,
                 powerups, shake, field, banner, economy,
                 UFO_SPAWN_INTERVAL_S, ufo_spawner=spawner, ufos=ufos)
    assert len(ufos) == 1  # live play at the interval spawns the saucer


# --- draw smoke -------------------------------------------------------------


def test_ufo_draw_renders_headless():
    """The inked saucer renders under the SDL dummy drivers: something drew
    (the surface changed), with no per-pixel alpha anywhere on the path."""
    pygame.init()
    paper = pygame.Surface((200, 200))
    pristine = paper.copy()
    _updatable, _drawable, _asteroids, _shots, _ufos, _floaters, _powerups = make_groups()
    ufo = UFO()
    place_saucer(ufo, 100, 100)
    ufo.draw(paper)
    assert bytes(paper.get_buffer().raw) != bytes(pristine.get_buffer().raw)
