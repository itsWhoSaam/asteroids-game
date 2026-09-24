"""Chromatic comic outlines (visual V2): the ink/fringe/fill contract.

comicfx renders every outlined entity in three passes — black ink, the
red/cyan offset fringes, then the colored stroke. These tests pin that
stack as pixels (probe-verified against pygame 2.6.1's stroke geometry):
the entity color still lands on the hull band, the fringes flank it
horizontally, black ink closes the poles, and nothing renders past the
locked halo budget. They also re-pin the ring-band tripwire in its V2
form: the inked ship's outline never reaches the band where the shield
ring sits, 25–32px from the hull center.
"""

import pygame

from comicfx import FRINGE_MAX_PX, FRINGE_PX, chromatic_circle, chromatic_polygon
from constants import (
    LINE_WIDTH,
    PALETTE,
    PLAYER_RADIUS,
    POWERUP_SHIELD_RING_GAP,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from powerups import PowerUpType
from player import Player

INK_PIXEL = (0, 0, 0, 255)


def palette_pixel(name):
    return (*PALETTE[name], 255)


def probe_screen():
    """A paper-filled headless screen to draw probe shapes onto."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen.fill(PALETTE["paper"])
    return screen


def test_fringe_width_is_locked_at_or_under_three_px():
    """Blueprint lock: the chromatic fringe stays at 2px, never above the
    3px ceiling — the ring-band tripwire leaves ~5px of halo budget past
    the hull and the fringes must not spend it."""
    assert FRINGE_PX == 2
    assert FRINGE_PX <= FRINGE_MAX_PX <= 3


def test_circle_stack_paints_fill_fringes_and_ink():
    """A chromatic circle shows its color on the hull band, flanked by the
    fringe pair (red bleeds left, cyan right) with black ink at the poles."""
    screen = probe_screen()
    center = (320, 240)
    radius = 40
    chromatic_circle(screen, PALETTE["shot"], center, radius, LINE_WIDTH)

    def ray(offset, dx=0, dy=0):
        return screen.get_at((center[0] + dx * offset, center[1] + dy * offset))

    # the colored stroke still lands on the hull band — sampled at the
    # bottom pole, away from where the horizontal fringes bleed
    assert any(
        ray(o, dy=1) == palette_pixel("shot")
        for o in range(radius - LINE_WIDTH, radius)
    )

    # the fringes flank the stroke just past it, one color per side
    left = [ray(-o, dx=1) for o in range(radius + 1, radius + FRINGE_PX + 2)]
    right = [ray(o, dx=1) for o in range(radius + 1, radius + FRINGE_PX + 2)]
    assert palette_pixel("fringe_r") in left
    assert palette_pixel("fringe_c") in right

    # black ink closes the stack at the poles, past the colored stroke
    top = [ray(-o, dy=1) for o in range(radius + 1, radius + LINE_WIDTH + FRINGE_PX + 1)]
    assert any(pixel == INK_PIXEL for pixel in top)


def test_circle_outline_stays_inside_the_halo_budget():
    """Nothing renders beyond the ink edge: the outermost non-paper pixel
    sits within radius + width + FRINGE_PX (+1px rounding slop) of the
    center — an outlined entity may grow by the ink width, never more."""
    screen = probe_screen()
    center = (320, 240)
    radius = 40
    chromatic_circle(screen, PALETTE["shot"], center, radius, LINE_WIDTH)

    limit = radius + LINE_WIDTH + FRINGE_PX + 1
    reach = limit + 6
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            if dx * dx + dy * dy > limit * limit:
                assert screen.get_at((center[0] + dx, center[1] + dy)) == palette_pixel("paper")


def test_polygon_stack_paints_fill_fringes_and_ink():
    """The ship's triangle gets the same stack: hull color, both fringes,
    and ink all land inside its bounding box."""
    screen = probe_screen()
    center = pygame.Vector2(320, 240)
    forward = pygame.Vector2(0, 1) * PLAYER_RADIUS
    side = pygame.Vector2(0, 1).rotate(90) * (PLAYER_RADIUS / 1.5)
    points = [center + forward, center - forward - side, center - forward + side]

    chromatic_polygon(screen, PALETTE["ship"], points, LINE_WIDTH)

    box = [
        screen.get_at((x, y))
        for x in range(280, 361)
        for y in range(200, 281)
    ]
    assert palette_pixel("ship") in box
    assert palette_pixel("fringe_r") in box
    assert palette_pixel("fringe_c") in box
    assert INK_PIXEL in box


def test_unshielded_ship_outline_never_reaches_the_ring_band():
    """V2 form of the ring-band tripwire: with no shield stocked, the inked
    ship (hull + fringes + ink) must leave the whole band where the shield
    ring would sit — offsets 25–32px from center — all paper."""
    screen = probe_screen()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.draw(screen)

    ring = PLAYER_RADIUS + POWERUP_SHIELD_RING_GAP
    band = range(ring - 3, ring + 5)  # offsets 25..32
    for side in (1, -1):
        for offset in band:
            x = int(SCREEN_WIDTH / 2) + side * offset
            assert screen.get_at((x, int(SCREEN_HEIGHT / 2))) == palette_pixel("paper")


def test_shielded_ring_still_lands_in_its_band():
    """With a charge stocked, the chromatic ring still paints the band —
    the shield stays visible above the inked hull."""
    screen = probe_screen()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.activate_powerup(PowerUpType.SHIELD)
    player.draw(screen)

    ring = PLAYER_RADIUS + POWERUP_SHIELD_RING_GAP
    band = range(ring - 3, ring + 5)
    assert any(
        screen.get_at((int(SCREEN_WIDTH / 2) + offset, int(SCREEN_HEIGHT / 2)))
        != palette_pixel("paper")
        for offset in band
    )
