"""Insanity chaos: mystery & curse pickups — the pure drop/open rolls, the
curse wiring through the player and the sweep, the bomb's field clear,
pierce survival, and homing steering.

Failure signatures the tests must catch (spec): a curse timer that never
expires; a bomb or curse that touches the combo (the locked decision: combo
counts shot kills only); a piercing shot that dies on a rock; a homing shot
that changes speed; a mystery open that never logs.
"""

import json
import random
from collections import defaultdict

import pygame
import pytest

import blackhole
from asteroid import Asteroid, Boss
from constants import (
    ASTEROID_MIN_RADIUS,
    CURSE_REVERSE_S,
    HOMING_TURN_RATE_S,
    MYSTERY_COLOR,
    MYSTERY_CURSE_CHANCE,
    MYSTERY_DROP_CHANCE,
    PALETTE,
    POWERUP_DURATION_S,
    SHAKE_BOMB,
)
from game import Game
from main import HitStop, bomb_clear, destroyed_asteroids, handle_collisions
from particles import Shake
from player import Player
from powerups import (
    BUFF_TYPES,
    CURSE_TYPES,
    PowerUp,
    PowerUpType,
    drop_type,
    mystery_pick_type,
)
from shot import Shot, homing_steer


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


@pytest.fixture(autouse=True)
def _class_state_reset():
    """Class/module-level state resets: main publishes these every frame at
    runtime, but tests arm them directly — neither may leak into the next
    test (a stray homing group or gravity well would bend the physics)."""
    Shot.homing_targets = None
    blackhole.live_holes.clear()
    yield
    Shot.homing_targets = None
    blackhole.live_holes.clear()


# --- The pure rolls ------------------------------------------------------------


def test_mystery_open_bounds_pin_the_gamble():
    """The first 25% of the roll is the sting: reverse then disarm, equal
    odds; the boundary roll itself falls to the buffs (strict <); the
    modulo clamp keeps a sloppy 1.0 roll on a real buff."""
    assert mystery_pick_type(0.0) is PowerUpType.REVERSE
    assert mystery_pick_type(0.124) is PowerUpType.REVERSE
    assert mystery_pick_type(0.125) is PowerUpType.DISARM
    assert mystery_pick_type(MYSTERY_CURSE_CHANCE) is PowerUpType.SHIELD
    assert mystery_pick_type(0.9999) is PowerUpType.MAGNET
    assert mystery_pick_type(1.0) is PowerUpType.SHIELD  # clamped, never IndexError


def test_mystery_open_seeded_stream_covers_every_content():
    """A seeded stream lands on every buff and both curses, and the mapping
    is honest: curses come only from the sting band, buffs only from the
    rest — a curse pick outside the first 25% would mean the odds lie."""
    random.seed(99)
    rolls = [random.random() for _ in range(3000)]
    picks = [mystery_pick_type(roll) for roll in rolls]

    assert set(picks) == set(BUFF_TYPES) | set(CURSE_TYPES)
    for roll, pick in zip(rolls, picks):
        if pick in CURSE_TYPES:
            assert roll < MYSTERY_CURSE_CHANCE
        else:
            assert pick in BUFF_TYPES
            assert roll >= MYSTERY_CURSE_CHANCE


def test_drop_type_rolls_the_wildcard_share():
    """40% of paid drops are the ? wildcard (strict <), the rest an equal
    draw from the seven buffs, clamped at the top of the roll."""
    assert drop_type(0.0) is PowerUpType.MYSTERY
    assert drop_type(0.3999) is PowerUpType.MYSTERY
    assert drop_type(MYSTERY_DROP_CHANCE) is PowerUpType.SHIELD  # boundary: no wildcard
    assert drop_type(0.55) is PowerUpType.RAPID
    assert drop_type(1.0) is PowerUpType.MAGNET  # clamped, never IndexError


def test_drop_rate_seeded_stream_lands_near_the_wildcard_share():
    random.seed(7)
    kinds = [drop_type(random.random()) for _ in range(3000)]
    share = sum(kind is PowerUpType.MYSTERY for kind in kinds) / len(kinds)
    assert share == pytest.approx(MYSTERY_DROP_CHANCE, abs=0.03)


def test_chaos_constants_pin_the_starting_values():
    """The spec's playtest starting values, and the duration table's honest
    shape: timed effects have entries, instant and on-collect types do not
    (a duration for the bomb or disarm would be a lie the HUD would tell)."""
    assert MYSTERY_DROP_CHANCE == pytest.approx(0.40)
    assert MYSTERY_CURSE_CHANCE == pytest.approx(0.25)
    assert CURSE_REVERSE_S == pytest.approx(6.0)
    assert POWERUP_DURATION_S["reverse"] == pytest.approx(CURSE_REVERSE_S)
    assert HOMING_TURN_RATE_S == pytest.approx(360.0)
    assert SHAKE_BOMB == pytest.approx(12.0)
    assert MYSTERY_COLOR is PALETTE["powerup_mystery"]

    for kind in ("shield", "rapid", "triple", "pierce", "homing"):
        assert POWERUP_DURATION_S[kind] == pytest.approx(8.0)
    for kind in ("bomb", "disarm", "mystery"):
        assert kind not in POWERUP_DURATION_S


# --- Mystery collection & curses through the sweep ------------------------------


def test_mystery_collects_into_a_buff_through_the_sweep(tmp_path, monkeypatch):
    """A ? pickup resolves on collect: one roll, a buff arm, both events —
    mystery_collected for the open, powerup_collected for the content."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    PowerUp(100, 660, PowerUpType.MYSTERY)
    monkeypatch.setattr(random, "random", lambda: 0.5)  # the open: a buff

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 0
    assert player.has_triple
    events = read_events(tmp_path)
    assert sum(e["type"] == "mystery_collected" for e in events) == 1
    collected = [e for e in events if e["type"] == "powerup_collected"]
    assert [e["powerup_type"] for e in collected] == ["triple"]
    assert sum(e["type"] == "curse_revealed" for e in events) == 0


def test_curse_reveal_logs_the_sting_and_never_the_jingle(tmp_path, monkeypatch):
    """A curse open: mystery_collected + curse_revealed, and no
    powerup_collected — the pickup jingle would be a lie about what just
    happened."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    PowerUp(100, 660, PowerUpType.MYSTERY)
    monkeypatch.setattr(random, "random", lambda: 0.1)  # the sting: reverse

    handle_collisions(asteroids, shots, player, game, powerups)

    assert player.cursed_reverse
    assert player.powerup_timers[PowerUpType.REVERSE.value] == pytest.approx(
        CURSE_REVERSE_S
    )
    events = read_events(tmp_path)
    assert sum(e["type"] == "mystery_collected" for e in events) == 1
    revealed = [e for e in events if e["type"] == "curse_revealed"]
    assert [e["curse"] for e in revealed] == ["reverse"]
    assert sum(e["type"] == "powerup_collected" for e in events) == 0


def test_reverse_controls_flip_while_the_curse_runs(monkeypatch):
    """One sign flips every answer: the same W key that flies the ship
    forward flies it backward while the curse clock runs."""
    pygame.init()

    def update_with_thrust(player):
        # defaultdict: pygame's real key state answers 0 for every key the
        # update touches that the test didn't press — a plain dict KeyErrors.
        pressed = defaultdict(int)
        pressed[pygame.K_w] = 1
        monkeypatch.setattr(pygame.key, "get_pressed", lambda: pressed)
        player.update(0.1)
        return player.position

    normal = update_with_thrust(Player(640, 360))
    cursed = Player(640, 360)
    cursed.activate_powerup(PowerUpType.REVERSE)
    assert cursed.cursed_reverse
    cursed = update_with_thrust(cursed)

    # rotation 0 faces (0, 1): thrust moves +y normally, -y cursed.
    assert normal.y > 360
    assert cursed.y < 360


def test_curse_timer_expires(monkeypatch):
    """The never-expire curse is a named failure signature: the clock must
    empty and the controls must answer honestly again."""
    pygame.init()
    player = Player(640, 360)
    player.activate_powerup(PowerUpType.REVERSE)

    pressed = defaultdict(int)
    pressed[pygame.K_w] = 1
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: pressed)
    player.update(CURSE_REVERSE_S)

    assert not player.cursed_reverse
    assert PowerUpType.REVERSE.value not in player.powerup_timers


def test_disarm_strips_everything_on_reveal(tmp_path, monkeypatch):
    """The disarm reveal: the shield's unspent charge and every running
    effect evaporate at once — and the curse arms no clock of its own."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.SHIELD)
    player.activate_powerup(PowerUpType.RAPID)
    PowerUp(100, 660, PowerUpType.MYSTERY)
    monkeypatch.setattr(random, "random", lambda: 0.13)  # the sting: disarm

    handle_collisions(asteroids, shots, player, game, powerups)

    assert player.powerup_timers == {}
    assert player.shield_hits == 0
    assert not player.shielded
    assert not player.has_rapid
    revealed = [e for e in read_events(tmp_path) if e["type"] == "curse_revealed"]
    assert [e["curse"] for e in revealed] == ["disarm"]


# --- The bomb: instant field clear -----------------------------------------------


def test_bomb_fires_the_injected_callback_without_arming_a_clock():
    """The bomb is instant: its callback fires once, and no duration lands
    in the timers — nothing about it is timed."""
    pygame.init()
    player = Player(640, 360)
    fired = []
    player.bomb_field = lambda: fired.append(True)

    player.activate_powerup(PowerUpType.BOMB)

    assert fired == [True]
    assert PowerUpType.BOMB.value not in player.powerup_timers


def test_bomb_without_a_callback_is_a_safe_no_op():
    """A player built outside main() has no callback wired yet: the bomb
    must degrade, not crash."""
    pygame.init()
    player = Player(640, 360)
    player.activate_powerup(PowerUpType.BOMB)
    assert player.powerup_timers == {}


def test_bomb_clear_splits_the_field_through_the_nuke_path(tmp_path):
    """The bomb's clear is the bought nuke's exact path: every rock dies
    through the ordinary destruction diff — the boss included, killed not
    exempted — the multi beat freezes, the screen rocks, and the combo
    never hears about it (locked decision: combo counts shot kills)."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)  # out of the blast's way: no player hit
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    Asteroid(200, 200, ASTEROID_MIN_RADIUS * 2)
    Asteroid(400, 200, ASTEROID_MIN_RADIUS * 3)
    Boss(600, 200, 1)
    prev = set(asteroids)
    hit_stop = HitStop()
    shake = Shake()

    bomb_clear(hit_stop, shake, asteroids)

    assert len(asteroids) == 0
    wrecks = destroyed_asteroids(prev, asteroids)
    assert any(isinstance(wreck, Boss) for wreck in wrecks)
    # All three wrecks mint (the capstone payoff): the boss's death is a
    # paid destruction like any other, and the bomb is still no credit
    # wreck for the economy diff beyond the ordinary payouts.
    assert sum(wreck.mintable for wreck in wrecks) == 3
    assert hit_stop.frozen  # several deaths in one call: the multi beat
    assert shake.magnitude > 0  # the screen rocks
    assert game.combo.chain == 0  # combo-free, exactly like the nuke


def test_bomb_through_the_sweep_pays_credits_via_the_diff(tmp_path, monkeypatch):
    """Collecting a ? that resolves to a bomb wipes the field mid-sweep;
    the plain rocks then flow through the destruction diff as mintable
    wrecks — combo-free — the same as a bought nuke."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    Asteroid(200, 200, ASTEROID_MIN_RADIUS * 2)
    Asteroid(400, 200, ASTEROID_MIN_RADIUS * 3)
    prev = set(asteroids)
    hit_stop = HitStop()
    shake = Shake()
    player.bomb_field = lambda: bomb_clear(hit_stop, shake, asteroids)
    PowerUp(100, 660, PowerUpType.MYSTERY)
    monkeypatch.setattr(random, "random", lambda: 0.84)  # the open: a bomb

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(asteroids) == 0
    assert game.combo.chain == 0
    wrecks = destroyed_asteroids(prev, asteroids)
    assert len(wrecks) == 2
    assert all(wreck.mintable for wreck in wrecks)
    events = read_events(tmp_path)
    collected = [e for e in events if e["type"] == "powerup_collected"]
    assert [e["powerup_type"] for e in collected] == ["bomb"]


# --- Pierce ----------------------------------------------------------------------


def test_pierce_lets_the_shot_drill_through_a_rock(tmp_path):
    """PIERCE: the shot survives the hit — the rock dies, its children
    spawn, and the bullet flies on."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)  # far from the fight: no player hit
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.PIERCE)
    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 2)
    Shot(640, 360)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(asteroids) == 2  # the medium split into two smalls
    assert len(shots) == 1 and next(iter(shots)).alive()  # drilled through


def test_without_pierce_the_shot_still_dies_on_impact(tmp_path):
    """The default contract holds: no buff, the shot is spent on the rock."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 2)
    Shot(640, 360)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(asteroids) == 2
    assert len(shots) == 0


def test_pierce_dies_on_the_boss_instead_of_melting_the_pool(tmp_path):
    """A piercing shot drills rocks, not the boss: it dies on the hull like
    any other, so one pass can never shred the whole HP pool per frame."""
    pygame.init()
    _, _, asteroids, shots, powerups = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.PIERCE)
    boss = Boss(640, 360, 1)
    Shot(640, 360)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert boss.alive()
    assert boss.hp == boss.max_hp - 1  # exactly one shot's worth
    assert len(shots) == 0  # the hull ate the bullet
    assert game.score == 0  # no kill paid


# --- Homing ----------------------------------------------------------------------


def angle_between(a, b):
    return abs(a.normalize().angle_to(b.normalize()))


def test_homing_steer_preserves_speed_and_bounds_the_turn():
    """The pure math: speed is preserved, and one frame turns the heading
    toward the target by exactly turn_rate·dt — never more."""
    position = pygame.Vector2(0, 0)
    velocity = pygame.Vector2(100, 0)
    target = pygame.Vector2(100, 100)  # 45 degrees off the heading

    steered = homing_steer(position, velocity, [target], HOMING_TURN_RATE_S, 0.1)

    assert steered.length() == pytest.approx(velocity.length())
    before = angle_between(velocity, target - position)
    after = angle_between(steered, target - position)
    assert after == pytest.approx(before - HOMING_TURN_RATE_S * 0.1)  # a 36° step
    assert after < before  # it turned toward the target, not away


def test_homing_steer_passes_through_when_there_is_nothing_to_steer_to():
    position = pygame.Vector2(0, 0)
    velocity = pygame.Vector2(100, 0)
    assert homing_steer(position, velocity, [], 360.0, 0.1) == velocity
    assert (
        homing_steer(position, pygame.Vector2(0, 0), [pygame.Vector2(50, 0)], 360.0, 0.1)
        == pygame.Vector2(0, 0)
    )


def test_homing_steer_converges_on_the_nearest_target():
    """Enough bounded steps align the heading with the nearest rock — the
    buff bends bullets, it does not teleport them."""
    position = pygame.Vector2(0, 0)
    velocity = pygame.Vector2(100, 0)
    near = pygame.Vector2(100, 100)
    far = pygame.Vector2(-500, 500)

    steered = velocity
    for _ in range(60):
        steered = homing_steer(position, steered, [far, near], HOMING_TURN_RATE_S, 0.1)

    near_miss = angle_between(steered, near - position)
    far_miss = angle_between(steered, far - position)
    assert near_miss < 1.0  # converged on the near rock...
    assert far_miss > near_miss + 45.0  # ...and the far rock lost by a mile


def test_homing_hook_steers_live_shots_only_while_armed():
    """The class-level hook (the speed_scale precedent): main publishes the
    asteroid group while HOMING runs; None re-arms straight flight."""
    pygame.init()
    _, _, asteroids, shots, _ = make_groups()
    Asteroid(0, 200, ASTEROID_MIN_RADIUS)  # below the shot's +x heading
    shot = Shot(0, 0)
    shot.velocity = pygame.Vector2(100, 0)

    Shot.homing_targets = asteroids
    shot.update(0.1)
    assert shot.velocity.y > 0  # steered toward the rock

    Shot.homing_targets = None
    shot.velocity = pygame.Vector2(100, 0)
    shot.update(0.1)
    assert shot.velocity.y == 0  # straight flight re-armed
