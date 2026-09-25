"""Palette contract (visual V1): every color site resolves from PALETTE.

constants.PALETTE is the single place color lives — entity draws, the two
screen fills, and the HUD text constant all read it, and the pixel tests
assert against these same entries, so a palette regrade moves the whole
game (tests included) in one diff. These tests pin that routing, not the
specific swatches: the hues are a tunable identity, not a contract.
"""

import pygame

from asteroid import Asteroid, asteroid_color
from constants import HUD_COLOR, PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH
from particles import Particle
from player import Player
from powerups import PowerUp, PowerUpType, powerup_color
from shot import Shot


def palette_pixel(name):
    """The opaque pixel a palette entry renders as on screen."""
    return (*PALETTE[name], 255)


def draws_expected_color(screen, sprite, expected_name, box):
    """Draw one sprite over paper and return whether any pixel shows the
    expected palette color — the entity resolved its hue from the table."""
    screen.fill(PALETTE["paper"])
    sprite.draw(screen)
    expected = palette_pixel(expected_name)
    return any(screen.get_at(pos) == expected for pos in box)


def test_every_palette_entry_is_an_rgb_tuple_in_range():
    for name, color in PALETTE.items():
        assert len(color) == 3, name
        assert all(
            isinstance(channel, int) and 0 <= channel <= 255 for channel in color
        ), name


def test_hud_color_constant_routes_through_the_palette():
    """The F1 HUD text constant is a palette alias, not a second color source."""
    assert HUD_COLOR is PALETTE["hud_ink"]


def test_asteroid_color_resolves_by_size_tier():
    assert asteroid_color(20) is PALETTE["asteroid_s"]
    assert asteroid_color(40) is PALETTE["asteroid_m"]
    assert asteroid_color(60) is PALETTE["asteroid_l"]
    # out-of-band radii clamp into the tier band instead of KeyError
    assert asteroid_color(5) is PALETTE["asteroid_s"]
    assert asteroid_color(600) is PALETTE["asteroid_l"]


def test_powerup_color_resolves_per_kind():
    assert powerup_color(PowerUpType.SHIELD) is PALETTE["powerup_shield"]
    assert powerup_color(PowerUpType.RAPID) is PALETTE["powerup_rapid"]
    assert powerup_color(PowerUpType.TRIPLE) is PALETTE["powerup_triple"]
    # the ? wildcard's violet is a palette alias, not a second color source
    assert powerup_color(PowerUpType.MYSTERY) is PALETTE["powerup_mystery"]


def test_player_draws_its_hull_in_the_ship_color():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    box = [(x, y) for x in range(600, 681, 2) for y in range(320, 401, 2)]
    assert draws_expected_color(screen, player, "ship", box)


def test_shot_draws_in_the_shot_color():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    shot = Shot(640, 360)
    box = [(x, 360) for x in range(631, 650)]
    assert draws_expected_color(screen, shot, "shot", box)


def test_asteroid_draws_its_tier_color():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    asteroid = Asteroid(640, 360, 40)  # medium tier
    box = [(640, y) for y in range(394, 406)]  # the bottom stroke band at r=40
    assert draws_expected_color(screen, asteroid, "asteroid_m", box)


def test_particle_draws_in_the_spark_color():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    spark = Particle(640, 360, pygame.Vector2(0, 0))

    screen.fill(PALETTE["paper"])
    spark.draw(screen)

    assert screen.get_at((640, 360)) == palette_pixel("spark")


def test_powerup_draws_its_identity_color():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pickup = PowerUp(640, 360, PowerUpType.RAPID)
    box = [(640, y) for y in range(342, 379)]
    assert draws_expected_color(screen, pickup, "powerup_rapid", box)
