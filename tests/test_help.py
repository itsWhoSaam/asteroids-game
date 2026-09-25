"""Tests for the Tier 1 help overlay: the keybind list is pinned to the live
handlers (every listed key is answered somewhere real, so the overlay cannot
lie), the toggle only engages during play, and the sheet draws headless over
the shared dim."""

import inspect

import pygame

from constants import (
    PAUSE_OVERLAY_DIM_ALPHA,
    PAUSE_OVERLAY_DIM_COLOR,
    POWERUPS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from hud import draw_help, help_keymap
from main import update_world
from player import Player
from shop import UPGRADES, powerup_name_for_key
import main as main_module


def pump_source():
    """The event pump's source: where every non-polled key handler lives."""
    return inspect.getsource(main_module)


def make_world(tmp_path):
    """A Game plus every real object update_world touches, saving to tmp_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, updatable, drawable


# --- The keymap contract: every listed key has a live handler ---------------


def test_every_pump_key_in_the_keymap_has_a_live_branch():
    """The overlay lists H, M, the volume brackets, P/Esc, and the end-screen
    R/Q — all answered by KEYDOWN branches in main's event pump. A key
    constant missing from the pump means the list promised a dead key."""
    src = pump_source()
    for key_const in (
        "pygame.K_h",  # the toggle itself
        "pygame.K_m",  # mute
        "pygame.K_LEFTBRACKET",  # volume down
        "pygame.K_RIGHTBRACKET",  # volume up
        "pygame.K_p",  # pause
        "pygame.K_ESCAPE",  # pause (alias)
        "pygame.K_r",  # restart
        "pygame.K_q",  # quit
    ):
        assert key_const in src, f"no live event-pump handler for {key_const}"
    assert "pygame.MOUSEBUTTONDOWN" in src, "no live handler for the Click row"


def test_every_polled_ship_key_in_the_keymap_is_read_by_the_player():
    """The ship rows (W A S D, Space) document keys Player.update polls each
    frame — pygame's polled movement never touches the event pump, so the
    live handler is the poll itself."""
    src = inspect.getsource(Player.update)
    for key_const in (
        "pygame.K_w",
        "pygame.K_a",
        "pygame.K_s",
        "pygame.K_d",
        "pygame.K_SPACE",
    ):
        assert key_const in src, f"Player.update never reads {key_const}"


def test_pump_routes_keys_to_the_shop_and_powerup_handlers():
    """The shop 1-4 and powerup 7-0 rows live because the pump really hands
    KEYDOWNs to Shop.handle_key and Shop.handle_powerup_key — the two
    handlers the tables below pin the actual bindings to."""
    src = pump_source()
    assert "shop.handle_key(" in src
    assert "shop.handle_powerup_key(" in src


def test_shop_rows_match_the_live_upgrade_bindings():
    """Shop rows derive from shop.UPGRADES itself — the same frozen defs the
    buyer reads — so the list cannot drift from what 1-4 actually buy."""
    shop_rows = [keys for group, keys, _ in help_keymap() if group == "Shop"]
    assert shop_rows == [defn.key_label for defn in UPGRADES]
    # The labels are the real KEYDOWN codes the pump hands to handle_key.
    assert [chr(defn.key) for defn in UPGRADES] == ["1", "2", "3", "4"]


def test_powerup_rows_match_the_live_powerup_bindings():
    """Powerup rows derive from constants.POWERUPS and resolve through the
    same key map the activation handler reads (powerup_name_for_key)."""
    powerup_rows = [keys for group, keys, _ in help_keymap() if group == "Powerup"]
    assert powerup_rows == [chr(defn["key"]) for defn in POWERUPS.values()]
    for defn in POWERUPS.values():
        assert powerup_name_for_key(defn["key"]) is not None


def test_keymap_rows_are_wellformed():
    """Every row is a non-empty (group, keys, action) triple, and the spec's
    required groups are all present."""
    rows = help_keymap()
    groups = {group for group, _, _ in rows}
    assert {"Ship", "Shop", "Powerup", "Audio", "Game", "Game over"} <= groups
    assert len(rows) >= 12
    for group, keys, action in rows:
        assert group and keys and action


# --- The toggle: UI state like pause, gated to live play --------------------


def test_help_toggle_only_engages_during_play(tmp_path):
    """A live run toggles freely; the game-over screen refuses (its R/Q
    prompt is the only UI there)."""
    pygame.init()
    game, *_ = make_world(tmp_path)

    assert game.help_open is False
    assert game.toggle_help() is True
    assert game.help_open is True
    assert game.toggle_help() is True
    assert game.help_open is False

    for _ in range(3):
        game.player_hit()
    assert game.state == "game_over"
    assert game.toggle_help() is False
    assert game.help_open is False


def test_game_over_closes_a_stale_help_list(tmp_path):
    """Losing the last life with help up must not cover the game-over R/Q
    prompt — game_over() clears the flag like it clears pause."""
    pygame.init()
    game, *_ = make_world(tmp_path)
    game.toggle_help()
    assert game.help_open is True

    game.game_over()

    assert game.help_open is False


def test_both_restart_hooks_start_a_fresh_run_help_free(tmp_path):
    """A fresh run never opens with the list up: restart() clears it, so
    either R hook (game-over or pause overlay) lands help-free."""
    pygame.init()
    game, *_ = make_world(tmp_path)
    game.toggle_help()
    assert game.help_open is True

    game.restart()

    assert game.help_open is False
    assert game.state == "playing"


def test_help_never_freezes_the_world(tmp_path):
    """Help dims, it does not pause: the same update_world call that would
    move a rock still moves it with the list up — pause is the freeze and
    this overlay must not quietly become a second one."""
    pygame.init()
    game, player, asteroids, shots, updatable, drawable = make_world(tmp_path)
    from asteroid import Asteroid
    from asteroidfield import AsteroidField
    from constants import ASTEROID_MIN_RADIUS
    from drones import DroneBay
    from economy import Economy
    from hud import WaveBanner
    from particles import Shake

    Asteroid.containers = (asteroids, updatable, drawable)
    AsteroidField.containers = updatable
    rock = Asteroid(120, 120, ASTEROID_MIN_RADIUS)
    rock.velocity = pygame.Vector2(90, 0)
    field = AsteroidField(game)
    economy = Economy(save_path=tmp_path / "idle_save.json")
    drones = DroneBay(economy)
    banner = WaveBanner()
    shake = Shake()

    game.toggle_help()
    assert game.help_open is True
    update_world(updatable, drones, asteroids, shots, player, game,
                 [], shake, field, banner, economy, 1 / 60)
    assert rock.position != (120, 120), "help froze the world — that is pause's job"


# --- Rendering: headless-safe over the shared dim ---------------------------


def test_help_overlay_render_smoke():
    """The overlay draws headless: the shared dim sheet blends over a white
    frame (surface alpha only — per-pixel alpha would break dummy drivers)."""
    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()

    screen.fill((255, 255, 255))
    draw_help(screen)  # smoke: must not raise under dummy drivers

    # A corner far from any text is the dim-over-white blend, not white.
    share = PAUSE_OVERLAY_DIM_ALPHA / 255
    corner = screen.get_at((SCREEN_WIDTH - 20, SCREEN_HEIGHT - 20))[:3]
    expected = tuple(
        round(PAUSE_OVERLAY_DIM_COLOR[i] * share + 255 * (1 - share))
        for i in range(3)
    )
    assert corner != (255, 255, 255)
    assert all(abs(corner[i] - expected[i]) <= 2 for i in range(3))


def test_help_stacks_over_the_pause_overlay():
    """Both overlays open at once renders cleanly: the paused dim, then the
    help dim + list on top — the stacked frame must not raise headless."""
    from hud import draw_pause

    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()

    screen.fill((255, 255, 255))
    draw_pause(screen)
    draw_help(screen)  # smoke: the z-order from main's render sequence
