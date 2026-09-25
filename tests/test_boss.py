"""Insanity threats + capstone payoff: the boss — pure tier math, the
HP-pool take_hit with the 70/40/15% minion ladder, chip immunity, the hit
flash, and the money contract (its death mints through the ordinary diff,
pays one guaranteed chaos-table drop, and scores through register_kill).

Failure signatures the tests must catch (spec): a boss that dies to click
chips; minions at the wrong thresholds; the boss exempted from the nuke or
restart; a death that skips the mint or drops nothing; a boss wave that
double-spawns or never advances.
"""

import json
import random

import pygame
import pytest

from asteroid import Asteroid, Boss, boss_tier
from asteroidfield import AsteroidField
from constants import (
    ASTEROID_MIN_RADIUS,
    BOSS_DRIFT_SPEED,
    BOSS_HIT_FLASH_S,
    BOSS_HP_PER_TIER,
    BOSS_POINTS,
    BOSS_RADIUS_TIERS,
    LINE_WIDTH,
    MINION_RADIUS_MULTIPLIER,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import WaveBanner, points_for
from powerups import BUFF_TYPES, PowerUp, PowerUpType, drop_type, powerup_color
from main import (
    destroyed_asteroids,
    handle_collisions,
    maybe_advance_wave,
    maybe_boss_wave,
    mint_destructions,
    nuke_field,
)
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
    # The boss payoff drops real pickups: the PowerUp joins the same
    # containers main wires, so the group test reads the actual spawn.
    PowerUp.containers = (powerups, updatable, drawable)

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    return game, field, player, asteroids, shots, powerups


@pytest.fixture(autouse=True)
def _boss_containers():
    """Boss() built outside make_world still needs groups: alive() is
    pygame's in-a-group check, and take_hit consults it."""
    pygame.init()
    Asteroid.containers = (
        pygame.sprite.Group(), pygame.sprite.Group(), pygame.sprite.Group()
    )
    yield


# --- the pure tier math -------------------------------------------------------


def test_boss_tier_climbs_then_caps():
    assert boss_tier(5) == 1
    assert boss_tier(10) == 2
    assert boss_tier(15) == 3
    assert boss_tier(20) == 3  # capped at the largest radius tier
    assert boss_tier(100) == 3


def test_boss_scales_radius_and_hp_by_tier():
    boss = Boss(400, 300, 1)
    assert boss.radius == ASTEROID_MIN_RADIUS * BOSS_RADIUS_TIERS[1]
    assert boss.max_hp == BOSS_HP_PER_TIER
    assert boss.hp == boss.max_hp

    heavy = Boss(400, 300, 3)
    assert heavy.max_hp == 3 * BOSS_HP_PER_TIER
    assert heavy.radius == ASTEROID_MIN_RADIUS * BOSS_RADIUS_TIERS[3]


# --- the HP pool ---------------------------------------------------------------


def test_take_hit_soaks_the_pool_and_reports_the_kill():
    boss = Boss(400, 300, 1)  # 6 hp
    for _ in range(5):
        assert not boss.take_hit()
        assert boss.alive()
    assert boss.take_hit() is True  # the killing blow reports exactly once
    assert not boss.alive()
    assert not boss.take_hit()  # a dead boss never re-reports


def test_boss_hit_events_flow(tmp_path):
    pygame.init()
    game, *_ = make_world(tmp_path)
    boss = Boss(400, 300, 1)
    boss.take_hit()

    events = [
        line for line in (tmp_path / "game_events.jsonl").read_text().splitlines()
        if "boss_hit" in line
    ]
    assert len(events) == 1  # one landed shot, one event


# --- the minion ladder ---------------------------------------------------------


def count_minions(asteroids):
    """The boss is itself an Asteroid in the group — count only minions."""
    return sum(1 for rock in asteroids if not isinstance(rock, Boss))


def test_minions_spawn_on_the_70_40_15_ladder(tmp_path):
    """A tier-2 boss (12 hp) crosses all three thresholds as the pool
    drains: two mediums each, spawned at the boss's position."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    boss = Boss(400, 300, 2)

    boss.hp = 9
    assert not boss.take_hit()  # 8/12 = 0.667 < 0.70: first checkpoint
    assert count_minions(asteroids) == 2

    boss.hp = 5
    assert not boss.take_hit()  # 4/12 = 0.333 < 0.40: second checkpoint
    assert count_minions(asteroids) == 4

    boss.hp = 2
    assert not boss.take_hit()  # 1/12 = 0.083 < 0.15: third checkpoint
    assert count_minions(asteroids) == 6

    minions = [rock for rock in list(asteroids) if rock is not boss]
    assert len(minions) == 6
    for minion in minions:
        assert minion.radius == ASTEROID_MIN_RADIUS * MINION_RADIUS_MULTIPLIER
        assert minion.position == boss.position


def test_minions_spawn_only_on_threshold_crossings(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    boss = Boss(400, 300, 1)

    boss.take_hit()  # 5/6 = 0.833: below no threshold
    assert count_minions(asteroids) == 0


def test_a_tier_one_boss_never_reaches_the_third_checkpoint(tmp_path):
    """Honest math: 15% of a 6-hp pool is under one hit — a tier-1 boss
    fields two minion waves, not a promised third."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    boss = Boss(400, 300, 1)

    for _ in range(4):  # hp 6 → 2: checkpoints at 4 (0.667) and 2 (0.333)
        boss.take_hit()
    assert count_minions(asteroids) == 4

    boss.take_hit()  # hp 1: 1/6 = 0.167 — still above the 0.15 checkpoint
    assert boss.alive()
    assert count_minions(asteroids) == 4  # tier 1 never fields the third wave

    boss.take_hit()  # the killing blow: hp 1 → 0
    assert not boss.alive()
    assert count_minions(asteroids) == 4  # death spawns nothing extra


# --- the money contract --------------------------------------------------------


def test_chip_clicks_never_kill_the_boss():
    boss = Boss(400, 300, 1)
    assert boss.take_chip(10_000) is False  # a mountain of chip damage
    assert boss.alive()
    assert boss.hp == boss.max_hp


def test_boss_death_mints_credits_through_the_diff(tmp_path):
    """The capstone payoff: a boss wreck is a paid destruction — the mint
    poll pays what any large rock pays (points_for × the income multiplier,
    1.0 at zero levels) right after logging the defeat."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    economy = Economy(save_path=tmp_path / "economy.json")
    boss = Boss(400, 300, 1)
    prev = set(asteroids)

    boss.kill()  # any death source: shots, the nuke, restart
    paid = mint_destructions(prev, asteroids, economy, game.stats, wave=5)

    assert paid == [(boss, points_for(boss.radius))]  # the ordinary payout
    assert economy.credits == points_for(boss.radius)  # 1.0 multiplier
    assert boss.mintable  # the data guard the poll reads


def test_defeat_pays_points_through_register_kill(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    boss = Boss(400, 300, 1)

    game.register_kill(boss.kill_points)
    assert game.score == BOSS_POINTS  # chain 1 pays ×1

    boss2 = Boss(400, 300, 1)
    game.register_kill(boss2.kill_points)  # chain 2, inside the window
    assert game.score == BOSS_POINTS + round(BOSS_POINTS * 1.25)


# --- death through the ordinary paths -------------------------------------------


def test_boss_split_kills_without_children(tmp_path):
    """split() is the nuke's and restart's death path: the boss dies with
    no children — and is never exempted from those clears."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    boss = Boss(400, 300, 3)

    boss.split()
    assert not boss.alive()
    assert len(asteroids) == 0


def test_nuke_clears_the_boss_through_the_ordinary_diff(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    boss = Boss(400, 300, 1)
    prev = set(asteroids)

    nuke_field(asteroids)

    wrecks = destroyed_asteroids(prev, asteroids)
    assert any(isinstance(wreck, Boss) for wreck in wrecks)
    assert all(wreck.mintable for wreck in wrecks)  # the boss pays too


# --- the boss-wave spawner -------------------------------------------------------


def test_maybe_boss_wave_spawns_on_the_multiple_only(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)

    game.wave = 4
    maybe_boss_wave(game, field)
    assert len(asteroids) == 0

    game.wave = 5
    field.start_wave()  # the fresh-wave guard: nothing spawned yet
    maybe_boss_wave(game, field)
    assert len(asteroids) == 1
    assert isinstance(list(asteroids)[0], Boss)
    assert field.spawned_this_wave == 1  # the boss counts as wave population

    maybe_boss_wave(game, field)  # the populated guard: never a double boss
    assert len(asteroids) == 1


def test_maybe_boss_wave_ignores_game_over(tmp_path):
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.wave = 5
    field.start_wave()
    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"

    maybe_boss_wave(game, field)

    assert len(asteroids) == 0


def test_boss_counts_as_the_wave_population(tmp_path):
    """The key invariant: once the boss dies and the field is cleared, the
    existing cleared-field advance moves to wave 6 unchanged."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.wave = 5
    field.start_wave()
    maybe_boss_wave(game, field)
    boss = list(asteroids)[0]

    boss.kill()
    maybe_advance_wave(game, field, WaveBanner())

    assert game.wave == 6


# --- The boss through the collision sweep (chaos-pickups corrections) --------


def test_player_shots_soak_the_boss_pool_through_the_sweep(tmp_path):
    """A player shot landing on the boss drains exactly one HP through the
    sweep — no split, no kill, no score — the hull, not a rock."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.wave = 5
    field.start_wave()
    maybe_boss_wave(game, field)
    boss = list(asteroids)[0]
    hp_before = boss.hp
    Shot(boss.position.x, boss.position.y)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert boss.alive()
    assert boss.hp == hp_before - 1
    assert game.score == 0


def test_the_killing_blow_through_the_sweep_pays_boss_points(tmp_path):
    """The shot that empties the pool kills the boss through the ordinary
    destruction paths and pays BOSS_POINTS via register_kill."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.wave = 5
    field.start_wave()
    maybe_boss_wave(game, field)
    boss = list(asteroids)[0]
    boss.hp = 1  # one shot from death
    Shot(boss.position.x, boss.position.y)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert not boss.alive()
    assert game.score == BOSS_POINTS


def test_boss_death_drops_exactly_one_pickup(tmp_path):
    """The capstone payoff: a boss death always pays one drop from the
    ordinary chaos tables — any roll, exactly one pickup, never zero."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.wave = 5
    field.start_wave()
    maybe_boss_wave(game, field)
    boss = list(asteroids)[0]
    # The boss spawns at screen center — the player's spot too. Step the
    # ship aside or the sweep's pickup pass collects the drop the same
    # frame it spawns, inside the player standing in the boss.
    player.position = pygame.Vector2(200, SCREEN_HEIGHT / 2)
    boss.hp = 1
    Shot(boss.position.x, boss.position.y)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert not boss.alive()  # the killing blow still landed
    assert len(powerups) == 1  # the guaranteed prize
    dropped = list(powerups)[0]
    assert dropped.kind in BUFF_TYPES + (PowerUpType.MYSTERY,)

    events = [
        json.loads(line)
        for line in (tmp_path / "game_events.jsonl").read_text().splitlines()
    ]
    spawned = [e for e in events if e["type"] == "powerup_spawned"]
    assert [e["powerup_type"] for e in spawned] == [dropped.kind.value]
    assert spawned[0]["boss"] is True  # the event marks the payoff source


def test_boss_drop_reads_the_same_chaos_tables(tmp_path, monkeypatch):
    """The guaranteed drop is not a special pool: the pinned roll produces
    exactly what drop_type hands any plain-rock drop."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.wave = 5
    field.start_wave()
    maybe_boss_wave(game, field)
    boss = list(asteroids)[0]
    player.position = pygame.Vector2(200, SCREEN_HEIGHT / 2)  # out of the drop
    boss.hp = 1
    Shot(boss.position.x, boss.position.y)
    monkeypatch.setattr(random, "random", lambda: 0.84)

    handle_collisions(asteroids, shots, player, game, powerups)

    dropped = list(powerups)[0]
    assert dropped.kind is drop_type(0.84)


def test_update_slides_a_dragged_boss_along_the_edge_instead_of_culling(tmp_path):
    """A black hole can drag the boss with real momentum (the sim caught an
    escape at 432 px/s), and the off-screen cull would end a boss wave for
    free — no fight, no defeat, no event. The boss can't be culled and
    slides along the edge instead: the wave advances only when it dies."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    boss = Boss(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2, 1)
    boss.velocity = pygame.Vector2(-5000, 0)  # a hole's accumulated drag

    for _ in range(30):  # half a second at -5000 px/s crosses any edge
        boss.update(1 / 60)

    assert boss.alive() and not boss.despawned  # never culled
    assert boss.position.x >= boss.radius  # clamped just inside the edge


# --- the capstone feedback: flash, armor rings, drift ----------------------------


def test_a_landed_shot_lights_the_flash_and_it_decays():
    """Hit feedback: a landed shot lights the hull for BOSS_HIT_FLASH_S of
    sim time, decays per update — so a pause holds the blink — and lands
    exactly at zero, never negative."""
    boss = Boss(400, 300, 1)
    assert boss.hit_flash == 0.0

    boss.take_hit()
    assert boss.hit_flash == BOSS_HIT_FLASH_S  # the hull lights

    for _ in range(6):  # 0.1 s of sim time
        boss.update(1 / 60)
    assert 0.0 < boss.hit_flash < BOSS_HIT_FLASH_S  # decaying

    boss.update(BOSS_HIT_FLASH_S)  # the blink is over
    assert boss.hit_flash == 0.0


def test_boss_draw_renders_rings_and_flash_headless(tmp_path):
    """The layered-armor look renders under the dummy driver: the flash
    ring rides the hull's outside while the timer runs and disappears with
    it — plain ink draws, no per-pixel alpha."""
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()
    boss = Boss(400, 300, 2)
    boss.take_hit()  # the flash is lit

    boss.draw(screen)
    probe = (
        int(boss.position.x + boss.radius + LINE_WIDTH),  # mid flash band
        int(boss.position.y),
    )
    assert screen.get_at(probe)[:3] == PALETTE["hud_ink"]  # the flash ring

    screen.fill((0, 0, 0))
    boss.hit_flash = 0.0
    boss.draw(screen)
    assert screen.get_at(probe)[:3] != PALETTE["hud_ink"]  # gone with the blink


def test_every_drop_rollable_kind_has_a_palette_color():
    """Table completeness: every kind drop_type can hand a pickup renders.
    PIERCE/HOMING/BOMB shipped without color keys and crashed on their
    first draw — the guaranteed boss drop rolls them every fight."""
    for kind in BUFF_TYPES + (PowerUpType.MYSTERY,):
        color = powerup_color(kind)
        assert isinstance(color, tuple) and len(color) == 3
        assert all(0 <= channel <= 255 for channel in color), \
            f"{kind.value} resolves to a real palette RGB"


def test_boss_drift_scales_with_the_difficulty_multiplier(tmp_path):
    """The capstone composition: the boss's drift speed scales by the
    mode's multiplier — Easy glides, Hard stalks. The wave_params boss
    dict stays mode-independent (pinned by the difficulty tests); the
    entity adapts at spawn."""
    game, field, player, asteroids, shots, powerups = make_world(tmp_path)
    game.wave = 5

    game.set_mode("easy")
    field.start_wave()
    maybe_boss_wave(game, field)
    easy_speed = list(asteroids)[0].velocity.length()
    boss = list(asteroids)[0]
    boss.kill()

    game.set_mode("hard")
    field.start_wave()  # resets the populated guard for the next spawn
    maybe_boss_wave(game, field)
    hard_speed = list(asteroids)[0].velocity.length()

    assert easy_speed == pytest.approx(BOSS_DRIFT_SPEED * 0.80)
    assert hard_speed == pytest.approx(BOSS_DRIFT_SPEED * 1.25)
    assert easy_speed < hard_speed
