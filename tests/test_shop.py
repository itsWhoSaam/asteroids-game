"""Tests for the upgrade shop: purchase gating through the Economy seams,
each effect observable in the game modules, the Drones placeholder, save
roundtrips, and a headless render of the bottom panel."""

import json

import pygame
import pytest

from asteroid import Asteroid
from constants import (
    ASTEROID_MIN_RADIUS,
    CLICK_DAMAGE_BASE,
    GAME_OVER_LINE_STEP,
    NANOBLADE_MULT_PER_LEVEL,
    PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS,
    PLAYER_SHOOT_COOLDOWN_SECONDS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHOP_BRIGHT_COLOR,
    SHOP_DIM_COLOR,
    SHOP_PANEL_BG,
    SHOP_PANEL_HEIGHT,
    UPGRADE_COSTS,
)
from economy import Economy
from hud import points_for
from main import FloatingText, click_damage
from player import Player
from shop import Shop, UPGRADES, affordability_color, cell_width


@pytest.fixture
def economy(tmp_path):
    """An Economy on a private save path (missing file → fresh defaults)."""
    return Economy(save_path=str(tmp_path / "game_save.json"))


@pytest.fixture
def player():
    return Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)


@pytest.fixture
def shop(economy, player):
    return Shop(economy, player)


def fund(economy, amount):
    """The test harness's hand on the ledger — real runs earn instead."""
    economy.credits = amount


# --- shop surface ---------------------------------------------------------


def test_upgrades_are_data_driven_and_cover_the_economy_names():
    """The defs carry identity, key, and copy; balance stays in UPGRADE_COSTS."""
    assert {defn.name for defn in UPGRADES} == set(UPGRADE_COSTS)
    assert [defn.key for defn in UPGRADES] == [
        pygame.K_1,
        pygame.K_2,
        pygame.K_3,
        pygame.K_4,
    ]
    for defn in UPGRADES:
        assert defn.key_label == chr(defn.key)
        assert defn.effect


def test_panel_geometry_stays_clear_of_hud_and_game_over():
    """The bottom strip must not reach the centered game-over overlay or the
    top-left HUD: the overlay's lowest line ends well above the panel."""
    panel_top = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT
    game_over_bottom = SCREEN_HEIGHT / 2 + GAME_OVER_LINE_STEP
    assert panel_top > game_over_bottom


# --- buying ---------------------------------------------------------------


def test_handle_key_buys_through_the_economy_seam(shop, economy):
    fund(economy, 10.0)
    purchase = shop.handle_key(pygame.K_1)
    assert purchase is not None
    assert purchase.name == "nanoblade"
    assert purchase.title == "Nanoblade"
    assert purchase.level == 1
    assert purchase.cost == 10.0
    assert economy.levels["nanoblade"] == 1
    assert economy.credits == 0.0


def test_handle_key_refuses_when_short_and_changes_nothing(shop, economy):
    fund(economy, 9.99)  # just under the nanoblade base cost
    assert shop.handle_key(pygame.K_1) is None
    assert economy.credits == 9.99
    assert all(level == 0 for level in economy.levels.values())


def test_non_shop_keys_fall_through_untouched(shop, economy):
    """F2's R/Q and the ship's movement keys are not shop keys."""
    fund(economy, 1000.0)
    for key in (
        pygame.K_r,
        pygame.K_q,
        pygame.K_w,
        pygame.K_a,
        pygame.K_s,
        pygame.K_SPACE,
    ):
        assert shop.handle_key(key) is None
    assert economy.credits == 1000.0
    assert all(level == 0 for level in economy.levels.values())


def test_affordability_gate_matches_the_buy_gate(shop, economy):
    """The panel's brightness rule and buy()'s gate agree at the boundary."""
    fund(economy, 10.0)  # exactly the nanoblade base cost
    assert shop.affordable("nanoblade")
    assert affordability_color(True) == SHOP_BRIGHT_COLOR
    fund(economy, 9.99)
    assert not shop.affordable("nanoblade")
    assert affordability_color(False) == SHOP_DIM_COLOR


# --- effects --------------------------------------------------------------


def test_nanoblade_raises_click_damage(shop, economy):
    assert click_damage(shop) == CLICK_DAMAGE_BASE
    fund(economy, 1000.0)
    shop.handle_key(pygame.K_1)
    assert click_damage(shop) == pytest.approx(
        CLICK_DAMAGE_BASE * NANOBLADE_MULT_PER_LEVEL
    )
    shop.handle_key(pygame.K_1)  # level 2
    assert click_damage(shop) == pytest.approx(
        CLICK_DAMAGE_BASE * NANOBLADE_MULT_PER_LEVEL**2
    )


def test_nanoblade_kills_a_small_rock_in_fewer_clicks(tmp_path):
    """The effect is observable in the game: a rock that took three base
    clicks dies in two once Nanoblade is bought (and splits as usual)."""
    asteroids = pygame.sprite.Group()
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    Asteroid.containers = (asteroids, updatable, drawable)
    try:
        economy = Economy(save_path=str(tmp_path / "game_save.json"))
        shop = Shop(economy, Player(0, 0))
        rock = Asteroid(400, 300, ASTEROID_MIN_RADIUS)
        while rock.alive():
            rock.take_chip(click_damage(shop))
        assert len(asteroids) == 0  # a small rock shatters — no children

        fund(economy, 10.0)
        shop.handle_key(pygame.K_1)  # Nanoblade Lv 1 → 1.8 per click
        rock = Asteroid(400, 300, ASTEROID_MIN_RADIUS)
        clicks = 0
        while rock.alive():
            rock.take_chip(click_damage(shop))
            clicks += 1
        assert clicks == 2
        assert len(asteroids) == 0
    finally:
        Asteroid.containers = ()


def test_fire_rate_drops_the_cooldown_multiplier(shop, economy, player):
    assert player.cooldown_mult == 1.0
    fund(economy, 1000.0)
    shop.handle_key(pygame.K_2)
    assert player.cooldown_mult == pytest.approx(0.88)
    player.shot_cooldown_timer = 0.0
    player.shoot()
    assert player.shot_cooldown_timer == pytest.approx(
        PLAYER_SHOOT_COOLDOWN_SECONDS * 0.88
    )


def test_fire_rate_respects_the_floor(shop, economy, player):
    """Past enough levels the raw multiplier undershoots the floor; the
    effective cooldown never drops below PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS."""
    fund(economy, 10**9)
    for _ in range(25):
        shop.handle_key(pygame.K_2)
    assert (
        PLAYER_SHOOT_COOLDOWN_SECONDS * player.cooldown_mult
        < PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS
    )
    player.shot_cooldown_timer = 0.0
    player.shoot()
    assert player.shot_cooldown_timer == PLAYER_SHOOT_COOLDOWN_FLOOR_SECONDS


def test_income_upgrade_scales_mint_through_the_seam(shop, economy):
    fund(economy, 1000.0)
    shop.handle_key(pygame.K_3)
    assert economy.income_multiplier() == pytest.approx(1.15)
    payout = economy.mint(ASTEROID_MIN_RADIUS)  # small tier → 100
    assert payout == pytest.approx(points_for(ASTEROID_MIN_RADIUS) * 1.15)
    assert economy.credits == pytest.approx(1000.0 - 50.0 + payout)

    shop.handle_key(pygame.K_3)  # level 2
    assert economy.income_multiplier() == pytest.approx(1.15**2)


# --- Drones placeholder ---------------------------------------------------


def test_drones_store_a_level_without_gameplay_effect(shop, economy, player):
    """Drones buy, level, and persist — but touch nothing else until the
    drones PR adds the turrets."""
    fund(economy, 100.0)
    before = {
        "click": click_damage(shop),
        "cooldown": player.cooldown_mult,
        "income": economy.income_multiplier(),
    }
    purchase = shop.handle_key(pygame.K_4)
    assert purchase is not None
    assert purchase.name == "drone"
    assert purchase.level == 1
    assert economy.levels["drone"] == 1
    assert economy.credits == 0.0
    assert click_damage(shop) == before["click"]
    assert player.cooldown_mult == before["cooldown"]
    assert economy.income_multiplier() == before["income"]


# --- persistence ----------------------------------------------------------


def test_shop_purchases_persist_through_the_save_roundtrip(tmp_path, shop, economy):
    """Buy through the shop keys, save, and a fresh boot reloads the levels
    and applies their effects."""
    fund(economy, 10**6)
    shop.handle_key(pygame.K_1)  # nanoblade, 10
    shop.handle_key(pygame.K_2)  # fire-rate, 25
    shop.handle_key(pygame.K_4)  # drone, 100
    economy.save()

    fresh = Economy(save_path=economy.save_path)
    assert fresh.levels == economy.levels
    assert fresh.credits == pytest.approx(economy.credits)

    fresh_player = Player(0, 0)
    Shop(fresh, fresh_player)  # boot applies loaded effect levels
    assert fresh_player.cooldown_mult == pytest.approx(0.88)

    with open(economy.save_path) as f:
        data = json.load(f)
    assert data["idle_levels"]["nanoblade"] == 1
    assert data["idle_levels"]["drone"] == 1


def test_loaded_fire_rate_levels_apply_at_boot(tmp_path):
    """A save carrying Fire-rate levels boots the ship on the purchased
    cooldown, not the stock one."""
    path = tmp_path / "game_save.json"
    path.write_text(
        json.dumps(
            {"high_score": 7, "idle_credits": 5.0, "idle_levels": {"fire_rate": 2}}
        )
    )
    economy = Economy(save_path=str(path))
    player = Player(0, 0)
    Shop(economy, player)
    assert player.cooldown_mult == pytest.approx(0.88**2)


# --- panel rendering ------------------------------------------------------


@pytest.fixture
def headless_screen():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    yield screen
    pygame.display.quit()


def test_draw_panel_renders_the_strip_headlessly(headless_screen, shop, economy):
    """The panel draws without error and paints its strip: a background-only
    pixel inside a cell proves the panel is on screen."""
    fund(economy, 60.0)
    headless_screen.fill("black")
    shop.draw_panel(headless_screen)

    x = int(3.5 * cell_width())  # inside the last cell, below both text lines
    y = SCREEN_HEIGHT - 8
    assert headless_screen.get_at((x, y)) == (*SHOP_PANEL_BG, 255)


def test_draw_panel_marks_affordable_cells_bright(headless_screen, shop, economy):
    """Every cell paints text; the affordable cell's line uses the bright
    color, the unaffordable one the dim color."""
    fund(economy, 0.0)  # nothing affordable
    headless_screen.fill("black")
    shop.draw_panel(headless_screen)
    assert _text_pixels(headless_screen, 0)

    fund(economy, 10.0)  # nanoblade affordable — its line brightens
    headless_screen.fill("black")
    shop.draw_panel(headless_screen)
    bright = _text_pixels(headless_screen, 0)
    assert any(pixel[:3] == SHOP_BRIGHT_COLOR for pixel in bright)


def _text_pixels(screen, cell_index):
    """Non-background pixels sampled across one cell's text area."""
    samples = []
    x0 = int(cell_index * cell_width() + 8)
    for x in range(x0, x0 + 120, 3):
        for y in range(
            SCREEN_HEIGHT - SHOP_PANEL_HEIGHT + 8,
            SCREEN_HEIGHT - SHOP_PANEL_HEIGHT + 52,
            3,
        ):
            pixel = screen.get_at((x, y))
            if pixel[:3] != SHOP_PANEL_BG:
                samples.append(tuple(pixel))
    return samples


def test_confirmation_float_reuses_the_floating_pattern(headless_screen):
    """A purchase confirmation is a FloatingText with a label override."""
    floaters = pygame.sprite.Group()
    FloatingText.containers = (floaters,)
    try:
        floater = FloatingText(
            200, 700, 0, label="Nanoblade Lv 1", color=SHOP_BRIGHT_COLOR
        )
        assert floater.surface.get_width() > 0
        assert floater.position.y == 700
        floater.update(0.1)
        assert floater.position.y < 700  # rising, same as payout floats
    finally:
        FloatingText.containers = ()
