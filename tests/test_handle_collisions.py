"""Regression tests for the collision sweep in main.handle_collisions.

Engagement F2 rewrote the sweep's contract deliberately: a player collision
no longer ends the process with SystemExit — it costs a life, and the run
only ends at zero lives, when the Game reaches its game_over state. The old
pinned `pytest.raises(SystemExit)` test below is that rewrite, not an
accident. F4 adds the pickups side of the sweep: drops on non-small
destruction and collection on player overlap.
"""

import json

import pygame

from asteroid import Asteroid
from constants import PLAYER_INVULNERABILITY_SECONDS, SCREEN_HEIGHT, SCREEN_WIDTH
from game import Game
from main import handle_collisions
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


def make_game(tmp_path, player, asteroids, shots, powerups=None):
    """A Game wired to the given world, saving into tmp_path."""
    return Game(player, asteroids, shots, powerups, save_path=tmp_path / "game_save.json")


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_player_collision_costs_a_life_but_not_the_process(tmp_path):
    """Pinned contract, deliberately rewritten for F2: the sweep used to end
    the process with SystemExit on the first hit. Now the hit costs one life
    and respawns the ship at center, velocity zeroed, inside the grace
    window — the process lives on."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()

    player = Player(100, 660)
    player.velocity = pygame.Vector2(120, -40)
    game = make_game(tmp_path, player, asteroids, shots)
    Asteroid(100, 660, 40)  # distance 0 <= 40 + PLAYER_RADIUS: overlapping

    handle_collisions(asteroids, shots, player, game, powerups)  # must not raise SystemExit

    assert game.lives == 2
    assert game.state == "playing"
    assert player.position == pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    assert player.velocity == pygame.Vector2(0, 0)
    assert player.invulnerable


def test_player_hit_event_still_logged_after_collision(tmp_path):
    """The player_hit event survives the contract change unchanged."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()

    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots)
    Asteroid(100, 660, 40)

    handle_collisions(asteroids, shots, player, game, powerups)

    events = read_events(tmp_path)
    assert sum(event["type"] == "player_hit" for event in events) == 1
    assert sum(event["type"] == "asteroid_shot" for event in events) == 0


def test_collision_at_zero_lives_reaches_game_over(tmp_path):
    """One life left: the same sweep that used to exit the process instead
    ends the run through the Game."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()

    player = Player(100, 660)
    player.invulnerability_timer = 0.0  # not inside a grace window
    game = make_game(tmp_path, player, asteroids, shots)
    game.lives = 1  # arrange: one life from game over
    Asteroid(100, 660, 40)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.lives == 0
    assert game.state == "game_over"
    assert sum(event["type"] == "game_over" for event in read_events(tmp_path)) == 1


def test_invulnerability_window_ignores_asteroid_collisions(tmp_path):
    """A respawning ship may sit right on an asteroid for the grace window:
    collisions during it cost no life and log no player_hit."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()

    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots)
    player.respawn()  # grace window on, ship now at center
    Asteroid(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2, 40)  # overlapping the ship

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.lives == 3
    assert game.state == "playing"
    assert sum(event["type"] == "player_hit" for event in read_events(tmp_path)) == 0


def test_invulnerability_expires_and_then_costs_a_life(tmp_path):
    """Past the grace window the same overlap costs a life again."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots)
    player.respawn()
    player.update(PLAYER_INVULNERABILITY_SECONDS + 0.1)  # burn the window
    assert not player.invulnerable

    Asteroid(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2, 40)
    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.lives == 2


def test_game_over_state_ignores_further_player_collisions(tmp_path):
    """Once the run is over, rocks drifting through the ship cost nothing:
    the state check guards the hit before it can resolve."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()

    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots)
    game.lives = 0
    game.state = "game_over"
    Asteroid(100, 660, 40)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.lives == 0
    assert game.state == "game_over"
    assert sum(event["type"] == "player_hit" for event in read_events(tmp_path)) == 0


def test_two_overlapping_shots_split_asteroid_exactly_once(tmp_path):
    """B3: a second overlapping shot in the same frame must not re-split an
    asteroid the first shot already killed (which yielded four children and
    duplicate events).

    Group iteration walks a copied list, so the killed asteroid object stays
    reachable for the rest of the sweep; the liveness guards and the
    idempotent split() keep the frame honest.
    """
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()

    player = Player(100, 660)  # far from the asteroid: no player hit
    Asteroid(640, 360, 40)
    Shot(640, 360)
    Shot(640, 360)  # both shots overlap the asteroid
    game = make_game(tmp_path, player, asteroids, shots)

    handle_collisions(asteroids, shots, player, game, powerups)

    # exactly one split: two children, not four
    assert len(asteroids) == 2
    events = read_events(tmp_path)
    assert sum(event["type"] == "asteroid_split" for event in events) == 1
    assert sum(event["type"] == "asteroid_shot" for event in events) == 1
