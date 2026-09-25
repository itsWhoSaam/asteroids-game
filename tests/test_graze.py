"""Tests for the near-miss graze bonus (Tier 3): a fast close pass — outside
the collision radius, inside the graze band — pays a small score bonus with
its own white pts popup over the near-miss site. The gates are pure (band,
speeds, invulnerability, per-pair cooldown) and the sweep wires them to the
live pair; the credit ledger is never touched — no destruction happens, so
the destruction-diff mint has nothing to pay for.
"""

import json

import pygame

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    GRAZE_BAND_PX,
    GRAZE_COOLDOWN_S,
    GRAZE_MIN_SPEED,
    GRAZE_POINTS,
    PLAYER_INVULNERABILITY_SECONDS,
    PLAYER_RADIUS,
    SCORE_COLOR,
    SCORE_POPUP_OFFSET_Y,
)
from economy import Economy
from game import Game
from main import (
    FloatingText,
    destroyed_asteroids,
    graze_pays,
    handle_collisions,
)
from player import Player


ROCK_RADIUS = ASTEROID_MIN_RADIUS * 2
COLLISION_DISTANCE = PLAYER_RADIUS + ROCK_RADIUS
FAST_PLAYER = 120.0
FAST_ROCK = 90.0


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    floaters = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    FloatingText.containers = (floaters, updatable, drawable)

    return updatable, drawable, asteroids, shots, powerups, floaters


def make_game(tmp_path, player, asteroids, shots, powerups=None):
    """A Game wired to the given world, saving into tmp_path."""
    return Game(player, asteroids, shots, powerups, save_path=tmp_path / "game_save.json")


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def band_rock(player, inset, speed, offset_y=0.0):
    """A rock riding the graze band: inset px inside the band's outer edge,
    moving at `speed` — pays by construction, collides never."""
    x = player.position.x + COLLISION_DISTANCE + inset
    rock = Asteroid(x, player.position.y + offset_y, ROCK_RADIUS)
    rock.velocity = pygame.Vector2(-speed, 0)  # crossing the hull's flank
    return rock


def pts_popups(floaters):
    return [f for f in floaters if f.label.endswith("pts")]


# --- pure band + gate resolution (graze_pays) ---------------------------------


def test_graze_inside_band_pays():
    """A close pass strictly outside the collision radius, inside the band."""
    assert graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                      COLLISION_DISTANCE, FAST_PLAYER, FAST_ROCK)


def test_graze_collision_distance_does_not_pay():
    """Touching is a hit, never a graze — the inner boundary is strict."""
    assert not graze_pays(COLLISION_DISTANCE, COLLISION_DISTANCE,
                          FAST_PLAYER, FAST_ROCK)
    assert not graze_pays(COLLISION_DISTANCE - 5.0, COLLISION_DISTANCE,
                          FAST_PLAYER, FAST_ROCK)


def test_graze_beyond_band_does_not_pay():
    """A polite distance pays nothing — the outer boundary holds."""
    assert not graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX + 1.0,
                          COLLISION_DISTANCE, FAST_PLAYER, FAST_ROCK)


def test_graze_band_outer_boundary_is_inclusive():
    """The band's far edge still pays: collision + GRAZE_BAND_PX exactly."""
    assert graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX,
                      COLLISION_DISTANCE, FAST_PLAYER, FAST_ROCK)


def test_graze_needs_a_moving_ship():
    """A parked ship is no dodge, even with the rock in the band."""
    assert not graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                          COLLISION_DISTANCE, GRAZE_MIN_SPEED - 1.0, FAST_ROCK)
    assert not graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                          COLLISION_DISTANCE, 0.0, FAST_ROCK)


def test_graze_needs_a_moving_rock():
    """A near-still rock is no dodge either — both bodies must move."""
    assert not graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                          COLLISION_DISTANCE, FAST_PLAYER, GRAZE_MIN_SPEED - 1.0)


def test_graze_speed_floor_is_inclusive():
    """Exactly the floor speed counts as meaningful — on both bodies."""
    assert graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                      COLLISION_DISTANCE, GRAZE_MIN_SPEED, GRAZE_MIN_SPEED)


def test_graze_invulnerable_never_pays():
    """The respawn blink suppresses the band — no post-respawn farming."""
    assert not graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                          COLLISION_DISTANCE, FAST_PLAYER, FAST_ROCK,
                          invulnerable=True)


def test_graze_cooldown_blocks_the_regraze_until_expired():
    """A paying pair re-arms only after its cooldown: live cooldown blocks,
    expiry (left ≤ 0) pays again."""
    assert not graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                          COLLISION_DISTANCE, FAST_PLAYER, FAST_ROCK,
                          cooldown_left=0.5)
    assert graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                      COLLISION_DISTANCE, FAST_PLAYER, FAST_ROCK,
                      cooldown_left=0.0)
    assert graze_pays(COLLISION_DISTANCE + GRAZE_BAND_PX / 2,
                      COLLISION_DISTANCE, FAST_PLAYER, FAST_ROCK,
                      cooldown_left=-3.0)


# --- live sweep wiring --------------------------------------------------------


def test_graze_awards_score_and_popup_at_the_near_miss_site(tmp_path):
    """The sweep pays the small bonus and floats the white pts popup over
    the rock — the same popup_style resolver the kill popups ride."""
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()

    player = Player(200, 620)
    player.velocity = pygame.Vector2(FAST_PLAYER, -20)
    game = make_game(tmp_path, player, asteroids, shots)
    rock = band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.score == GRAZE_POINTS
    popups = pts_popups(floaters)
    assert len(popups) == 1
    assert popups[0].label == f"+{GRAZE_POINTS} pts"
    assert popups[0].color == SCORE_COLOR
    # The popup sits a head above the rock — the near-miss site itself.
    assert popups[0].position.x == rock.position.x
    assert popups[0].position.y == rock.position.y - SCORE_POPUP_OFFSET_Y
    assert any(e["type"] == "graze_bonus" for e in read_events(tmp_path))


def test_graze_pays_no_credits(tmp_path):
    """Economy untouched: nothing died, so the destruction diff — the only
    mint path — has nothing to pay, and the ledger reads exactly zero."""
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()

    player = Player(200, 620)
    player.velocity = pygame.Vector2(FAST_PLAYER, -20)
    game = make_game(tmp_path, player, asteroids, shots)
    economy = Economy(save_path=tmp_path / "idle_save.json")
    band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK)

    prev = set(asteroids)  # the main loop's snapshot, one frame earlier
    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.score == GRAZE_POINTS  # score paid …
    assert destroyed_asteroids(prev, asteroids) == []  # … nothing destroyed …
    assert economy.credits == 0.0  # … so the mint pass pays nothing
    assert not [e for e in read_events(tmp_path) if e["type"] == "credit_minted"]


def test_graze_cooldown_is_per_pair(tmp_path):
    """Two rocks in the band each pay their own bonus (one pair's cooldown
    never blocks the other); an immediate re-pass pays nothing; the same
    pair pays again once its cooldown elapses."""
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()

    player = Player(200, 620)
    player.velocity = pygame.Vector2(FAST_PLAYER, -20)
    game = make_game(tmp_path, player, asteroids, shots)
    band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK, offset_y=-40.0)
    band_rock(player, inset=GRAZE_BAND_PX / 4, speed=FAST_ROCK, offset_y=40.0)

    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.score == 2 * GRAZE_POINTS

    # The very next frame — hovering on the flanks pays nothing.
    game.tick(1 / 60)
    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.score == 2 * GRAZE_POINTS
    assert len(pts_popups(floaters)) == 2  # no third popup appeared

    # Cooldown elapsed: the same pairs pay again.
    game.now += GRAZE_COOLDOWN_S + 0.1
    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.score == 4 * GRAZE_POINTS


def test_graze_not_paid_while_invulnerable(tmp_path):
    """A rock riding the band of a blinking ship pays nothing — the sweep
    hands the live timer to the pure gate, so respawn grace and dash
    i-frames (one timer) both suppress the bonus."""
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()

    player = Player(200, 620)
    player.velocity = pygame.Vector2(FAST_PLAYER, -20)
    game = make_game(tmp_path, player, asteroids, shots)
    band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK)
    player.invulnerability_timer = PLAYER_INVULNERABILITY_SECONDS

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.score == 0
    assert not pts_popups(floaters)


def test_graze_needs_a_moving_ship_in_the_sweep(tmp_path):
    """The sweep passes the real velocities: a parked ship next to a fast
    rock is not a dodge and pays nothing."""
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()

    player = Player(200, 620)  # velocity zero — the spawn default
    game = make_game(tmp_path, player, asteroids, shots)
    band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.score == 0
    assert not pts_popups(floaters)


def test_graze_not_paid_after_game_over(tmp_path):
    """The playing gate mirrors the hit branch: a dead run pays nothing."""
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()

    player = Player(200, 620)
    player.velocity = pygame.Vector2(FAST_PLAYER, -20)
    game = make_game(tmp_path, player, asteroids, shots)
    game.state = "game_over"
    band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert game.score == 0
    assert not pts_popups(floaters)


def test_restart_clears_graze_cooldowns(tmp_path):
    """Run-state wiring: both restart hooks land in Game.restart (the
    game-over R and the pause overlay's R through restart_run), so a fresh
    run can graze from its first frame even before the old cooldown would
    have expired."""
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()

    player = Player(200, 620)
    player.velocity = pygame.Vector2(FAST_PLAYER, -20)
    game = make_game(tmp_path, player, asteroids, shots)
    band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK)

    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.score == GRAZE_POINTS

    # Advance barely at all: without the restart clear, the pair's
    # cooldown would still be live.
    game.now += 0.1
    game.restart()
    assert game.graze_cooldowns == {}

    # A fresh run's fresh rock, the blink already elapsed.
    player.invulnerability_timer = 0.0
    player.velocity = pygame.Vector2(FAST_PLAYER, -20)
    band_rock(player, inset=GRAZE_BAND_PX / 2, speed=FAST_ROCK)
    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.score == GRAZE_POINTS
