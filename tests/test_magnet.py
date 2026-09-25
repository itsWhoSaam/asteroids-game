"""Tests for the magnet powerup (Tier 3): the pure attraction step, the 8 s
dt-timer duration, the drop-pool integration, and the hidden-while-zero HUD
tag.

The magnet is strictly a drop effect: it rides the POWERUP_TYPES pool and
the drop constants tables, and never reads the bought-powerup system (the
Economy-priced POWERUPS dict, keys 7–0) — the disjointness is pinned here.
"""

import json
import random

import pygame
import pytest

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import (
    ASTEROID_MIN_RADIUS,
    HUD_LINE_STEP,
    HUD_MARGIN,
    PALETTE,
    POWERUP_DURATION_S,
    POWERUP_MAGNET_MAX_SPEED,
    POWERUP_MAGNET_RADIUS,
    POWERUP_RADIUS,
    POWERUPS,
    SCORE_COLOR,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from economy import Economy
from game import Game
from hud import draw_hud
from main import (
    FloatingText,
    apply_magnet,
    handle_collisions,
    magnet_pullables,
    popup_style,
    restart_run,
    update_world,
)
from particles import Shake
from player import Player
from powerups import (
    POWERUP_TYPES,
    PowerUp,
    PowerUpType,
    magnet_pull,
    pick_type,
)
from drones import DroneBay
from shot import Shot


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
    AsteroidField.containers = (updatable,)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    FloatingText.containers = (floaters, updatable, drawable)

    return updatable, drawable, asteroids, shots, powerups, floaters


def make_game(tmp_path, player, asteroids, shots, powerups):
    """A Game wired to the given world, saving into tmp_path."""
    return Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")


def read_events(tmp_path):
    path = tmp_path / "game_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- Pure attraction vector ---------------------------------------------------


def test_pull_accelerates_toward_the_ship():
    """A resting body right of the ship gains leftward velocity — toward
    the attractor, never away."""
    velocity = magnet_pull(
        pygame.Vector2(840, 360),  # 200 px right of the ship
        pygame.Vector2(640, 360),
        pygame.Vector2(0, 0),
    )
    assert velocity.x < 0
    assert velocity.y == 0


def test_pull_is_a_force_not_a_teleport():
    """The step resolves a velocity; it never moves the body itself."""
    position = pygame.Vector2(840, 360)
    magnet_pull(position, pygame.Vector2(640, 360), pygame.Vector2(0, 0))
    assert position == pygame.Vector2(840, 360)


def test_no_pull_beyond_the_radius():
    """Outside the band a body keeps its velocity, whatever it is."""
    far = pygame.Vector2(640 + POWERUP_MAGNET_RADIUS + 50, 360)
    drift = pygame.Vector2(-30, 0)
    assert magnet_pull(far, pygame.Vector2(640, 360), drift) == drift


def test_the_boundary_sits_on_the_no_pull_side():
    """Exactly at the radius is not inside it — the drop roll's strict `<`
    convention."""
    at_rim = pygame.Vector2(640 + POWERUP_MAGNET_RADIUS, 360)
    drift = pygame.Vector2(30, 0)
    assert magnet_pull(at_rim, pygame.Vector2(640, 360), drift) == drift


def test_pull_strength_eases_with_distance():
    """Closer in, stronger: the falloff is monotonic toward the attractor —
    a body just inside the rim barely feels the field, one closing in is
    yanked."""
    ship = pygame.Vector2(640, 360)
    near = magnet_pull(pygame.Vector2(640 + 50, 360), ship, pygame.Vector2(0, 0))
    far = magnet_pull(pygame.Vector2(640 + 200, 360), ship, pygame.Vector2(0, 0))
    assert near.length() > far.length() > 0


def test_pull_scales_with_dt():
    """Same body, twice the frame: twice the velocity gain — force × time,
    not a fixed shove."""
    ship = pygame.Vector2(640, 360)
    position = pygame.Vector2(640 + 100, 360)
    one_frame = magnet_pull(position, ship, pygame.Vector2(0, 0), dt=1 / 60)
    two_frames = magnet_pull(position, ship, pygame.Vector2(0, 0), dt=2 / 60)
    assert two_frames.length() == pytest.approx(one_frame.length() * 2)


def test_pull_speed_is_capped():
    """A body already flying fast toward the ship cannot exceed the cap —
    the grab can never sling a pickup past the hull."""
    speeding = magnet_pull(
        pygame.Vector2(640 + 10, 360),
        pygame.Vector2(640, 360),
        pygame.Vector2(-POWERUP_MAGNET_MAX_SPEED * 2, 0),
    )
    assert speeding.length() == pytest.approx(POWERUP_MAGNET_MAX_SPEED)


def test_a_body_on_the_ship_is_left_alone():
    """Zero distance has no direction; untouched beats a divide-by-zero."""
    center = pygame.Vector2(640, 360)
    drift = pygame.Vector2(12, -4)
    assert magnet_pull(center, center, drift) == drift


# --- Duration on the dt-timer pattern ------------------------------------------


def test_magnet_runs_its_duration_then_expires():
    pygame.init()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)

    player.activate_powerup(PowerUpType.MAGNET)
    assert player.has_magnet
    assert player.magnet_timer == pytest.approx(POWERUP_DURATION_S["magnet"])

    player.update(POWERUP_DURATION_S["magnet"] / 2)
    assert player.has_magnet
    player.update(POWERUP_DURATION_S["magnet"] / 2)  # the full duration spent
    assert not player.has_magnet
    assert player.magnet_timer == 0.0


def test_no_pull_after_expiry(tmp_path):
    """The expired clock is the whole gate: apply_magnet leaves bodies be."""
    pygame.init()
    _, _, asteroids, shots, powerups, _floaters = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.MAGNET)
    player.update(POWERUP_DURATION_S["magnet"])  # the clock ran out

    pickup = PowerUp(600, 360, PowerUpType.TRIPLE)
    pickup.velocity = pygame.Vector2(-30, 0)

    apply_magnet(game, player, 1 / 60, [pickup])

    assert pickup.velocity == pygame.Vector2(-30, 0)


def test_pull_applies_while_active(tmp_path):
    pygame.init()
    _, _, asteroids, shots, powerups, _floaters = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.MAGNET)

    pickup = PowerUp(SCREEN_WIDTH / 2 + 200, 360, PowerUpType.TRIPLE)
    pickup.velocity = pygame.Vector2(0, 0)

    apply_magnet(game, player, 1 / 60, [pickup])

    assert pickup.velocity.x < 0  # now heading toward the ship


def test_no_pull_off_a_live_run(tmp_path):
    """Playing-only, mirroring the collection gate: a dead run collects
    nothing, so it magnetizes nothing either."""
    pygame.init()
    _, _, asteroids, shots, powerups, _floaters = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.MAGNET)
    game.state = "game_over"

    pickup = PowerUp(600, 360, PowerUpType.TRIPLE)
    pickup.velocity = pygame.Vector2(-30, 0)

    apply_magnet(game, player, 1 / 60, [pickup])

    assert pickup.velocity == pygame.Vector2(-30, 0)


# --- Drop-pool integration ------------------------------------------------------


def test_magnet_is_a_first_class_drop_with_its_duration():
    assert PowerUpType.MAGNET in POWERUP_TYPES
    assert POWERUP_DURATION_S["magnet"] == pytest.approx(8.0)


def test_shot_kill_spawns_a_magnet_pickup(tmp_path, monkeypatch):
    """The sweep's rolls: 0.0 wins the drop, 0.95 lands in MAGNET's band —
    the appended seventh of the uniform pool."""
    pygame.init()
    _, _, asteroids, shots, powerups, _floaters = make_groups()
    player = Player(100, 660)  # far from the wreck: no player hit
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    Asteroid(640, 360, ASTEROID_MIN_RADIUS * 2)  # medium: eligible
    Shot(640, 360)
    rolls = iter([0.0, 0.95])  # the drop roll, then the type roll
    monkeypatch.setattr(random, "random", lambda: next(rolls))

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 1
    pickup = next(iter(powerups))
    assert pickup.kind is PowerUpType.MAGNET
    assert pickup.position == pygame.Vector2(640, 360)
    spawned = [e for e in read_events(tmp_path) if e["type"] == "powerup_spawned"]
    assert len(spawned) == 1
    assert spawned[0]["powerup_type"] == "magnet"


def test_collecting_the_magnet_activates_it(tmp_path):
    pygame.init()
    _, _, asteroids, shots, powerups, _floaters = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    PowerUp(100, 660, PowerUpType.MAGNET)

    handle_collisions(asteroids, shots, player, game, powerups)

    assert len(powerups) == 0
    assert player.has_magnet
    collected = [e for e in read_events(tmp_path) if e["type"] == "powerup_collected"]
    assert len(collected) == 1
    assert collected[0]["powerup_type"] == "magnet"


def test_the_drop_system_stays_disjoint_from_the_bought_system():
    """Two powerup systems share this repo by design: the magnet joins the
    drop tables and never the bought POWERUPS dict (keys 7–0, Economy-
    priced) — and its pick_type band still resolves purely."""
    assert "magnet" not in POWERUPS
    assert pick_type(0.9) is PowerUpType.MAGNET


# --- Economy integrity -----------------------------------------------------------


def test_the_magnet_does_not_alter_economy_math(tmp_path):
    """The pull bends velocities, never the ledger: with the magnet live,
    a mint pays exactly what a fresh economy would pay."""
    pygame.init()
    _, _, asteroids, shots, powerups, _floaters = make_groups()
    player = Player(100, 660)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    economy = Economy(save_path=str(tmp_path / "idle_save.json"))
    baseline = Economy(save_path=str(tmp_path / "baseline_save.json"))
    player.activate_powerup(PowerUpType.MAGNET)

    pulled = economy.mint(ASTEROID_MIN_RADIUS * 2)
    plain = baseline.mint(ASTEROID_MIN_RADIUS * 2)

    assert pulled == plain
    assert economy.credits == baseline.credits


# --- Pullables: pickups + credit floats, nothing else ----------------------------


def credit_float(x, y, amount):
    """A credit float exactly as the mint poll spawns it."""
    style = popup_style("credits", amount)
    return FloatingText(x, y, amount, label=style.label, color=style.color,
                        magnetic=style.magnetic)


def points_float(x, y, amount):
    """A points popup exactly as the sweep spawns it."""
    style = popup_style("points", amount)
    return FloatingText(x, y, amount, label=style.label, color=style.color,
                        magnetic=style.magnetic)


def test_magnet_pullables_selects_pickups_and_credit_floats_only():
    pygame.init()
    pickup = PowerUp(200, 200, PowerUpType.SHIELD)
    credit = credit_float(100, 100, 50)
    points = points_float(100, 120, 50)
    notice = FloatingText(100, 140, 0, label="Nanoblade Lv 2",
                          color=SCORE_COLOR)  # shop/powerup notices: never

    selected = magnet_pullables([pickup], [credit, points, notice])

    assert pickup in selected
    assert credit in selected
    assert points not in selected
    assert notice not in selected


def test_the_resolver_marks_credits_magnetic_and_points_not():
    assert popup_style("credits", 50).magnetic is True
    assert popup_style("points", 50).magnetic is False


def test_a_magnetized_credit_float_slides_home_while_points_hold(tmp_path):
    pygame.init()
    _, _, asteroids, shots, powerups, floaters = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    player.activate_powerup(PowerUpType.MAGNET)
    credit = credit_float(SCREEN_WIDTH / 2 + 150, 360, 50)
    points = points_float(SCREEN_WIDTH / 2 + 150, 360, 50)

    apply_magnet(game, player, 1 / 60, magnet_pullables(powerups, floaters))

    assert credit.velocity.x < 0  # the credit bends toward the ship
    assert points.velocity == pygame.Vector2(0, 0)  # the popup holds its line


def test_credit_floats_rise_unchanged_without_a_magnet():
    """Zero default velocity: the dt-timer template's plain rise is intact
    for every float the magnet never touches."""
    pygame.init()
    points = points_float(400, 300, 100)
    points.update(0.5)
    assert points.alive() and points.position == pygame.Vector2(400, 280)


# --- Restart hooks ----------------------------------------------------------------


def test_both_restart_hooks_clear_the_magnet(tmp_path):
    """Game.restart and the R-key branch both funnel the reset: no magnet
    survives into a fresh run, and its pickups die with the old one."""
    pygame.init()
    _, _, asteroids, shots, powerups, _floaters = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    economy = Economy(save_path=str(tmp_path / "idle_save.json"))

    player.activate_powerup(PowerUpType.MAGNET)
    PowerUp(200, 200, PowerUpType.MAGNET)
    game.restart()  # hook 1
    assert not player.has_magnet and player.magnet_timer == 0.0
    assert len(powerups) == 0

    player.activate_powerup(PowerUpType.MAGNET)
    PowerUp(200, 200, PowerUpType.MAGNET)
    restart_run(game, economy, AsteroidField(game), WaveBannerShim(),
                asteroids)  # hook 2: the game-over / pause-overlay R branch
    assert not player.has_magnet and player.magnet_timer == 0.0
    assert len(powerups) == 0


class WaveBannerShim:
    """restart_run's banner (show on wave start, dt fade per frame) —
    pygame-free like the real one's."""

    def show(self, wave):
        self.wave = wave

    def update(self, dt):
        self.dt_seen = dt


# --- Full-frame integration --------------------------------------------------------


def test_update_world_pulls_an_in_band_pickup_this_frame(tmp_path):
    """One full sim step: the pull bends the velocity before the frame's
    updates integrate it — accelerate, then move, the drift's own order."""
    pygame.init()
    updatable, drawable, asteroids, shots, powerups, floaters = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = make_game(tmp_path, player, asteroids, shots, powerups)
    economy = Economy(save_path=str(tmp_path / "idle_save.json"))
    drones = DroneBay(economy)
    player.activate_powerup(PowerUpType.MAGNET)
    pickup = PowerUp(SCREEN_WIDTH / 2 + 100, 360, PowerUpType.TRIPLE)
    pickup.velocity = pygame.Vector2(0, 0)

    start = pygame.Vector2(pickup.position)
    update_world(updatable, drones, asteroids, shots, player, game,
                 powerups, Shake(), AsteroidField(game),
                 WaveBannerShim(), economy, 1 / 60, floaters=floaters)

    assert pickup.position.x < start.x  # moved toward the ship this frame


# --- Rendering: pickup identity + HUD tag (headless pixels) -------------------------


def magnet_tag_band():
    """The second-row right-edge region where the MAGNET tag seats."""
    return [
        (x, HUD_MARGIN + HUD_LINE_STEP + dy)
        for x in range(SCREEN_WIDTH - 200, SCREEN_WIDTH - HUD_MARGIN)
        for dy in range(0, 30)
    ]


def test_magnet_pickup_renders_its_identity_color_and_letter():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pickup = PowerUp(640, 360, PowerUpType.MAGNET)

    screen.fill(PALETTE["paper"])
    pickup.draw(screen)

    # the ring resolves through the palette — the magnet's green, like every
    # other kind's identity hue
    ring = [(640, y) for y in range(360 - POWERUP_RADIUS - 3,
                                    360 - POWERUP_RADIUS + 4)]
    expected = (*PALETTE["powerup_magnet"], 255)
    assert any(screen.get_at(pos) == expected for pos in ring)
    # and the letter is stamped mid-circle, like every other pickup
    box = [
        screen.get_at((640 + dx, 360 + dy))
        for dx in range(-8, 9, 2)
        for dy in range(-8, 9, 2)
    ]
    assert any(pixel != (*PALETTE["paper"], 255) for pixel in box)


def test_hud_magnet_tag_hidden_while_zero():
    """The lives/wave pattern: no tag slot until the clock is running —
    not even for an expired timer's zero."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    paper = (*PALETTE["paper"], 255)

    screen.fill(PALETTE["paper"])
    draw_hud(screen, 0)
    assert all(screen.get_at(pos) == paper for pos in magnet_tag_band())

    screen.fill(PALETTE["paper"])
    draw_hud(screen, 0, magnet=0.0)
    assert all(screen.get_at(pos) == paper for pos in magnet_tag_band())


def test_hud_magnet_tag_shows_remaining_seconds_in_the_effect_color():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    draw_hud(screen, 0, magnet=5.2)

    expected = (*PALETTE["powerup_magnet"], 255)
    assert any(screen.get_at(pos) == expected for pos in magnet_tag_band())


def test_magnet_pull_survives_the_headless_contract():
    """The pull is pure vector math over the shared cache — no per-pixel
    alpha surface, no wall clock — so a magnetized float renders like any
    other on the dummy drivers."""
    pygame.init()
    screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    credit = credit_float(400, 300, 50)
    credit.velocity = pygame.Vector2(-100, 0)  # as the magnet would bend it

    credit.draw(screen)
    credit.update(0.1)

    assert credit.surface.get_width() > 0
    assert credit.position.x == 390  # 100 px/s for a tenth of a second
