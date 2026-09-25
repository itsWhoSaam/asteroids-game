"""Procedural comic FX: the ink/fringe/fill contract, the comic background
split, and the onomatopoeia bursts.

comicfx renders every outlined entity in three passes — black ink, the
red/cyan offset fringes, then the colored stroke. These tests pin that
stack as pixels (probe-verified against pygame 2.6.1's stroke geometry):
the entity color still lands on the hull band, the fringes flank it
horizontally, black ink closes the poles, and nothing renders past the
locked halo budget. They also re-pin the ring-band tripwire in its V2
form: the inked ship's outline never reaches the band where the shield
ring sits, 25–32px from the hull center.

The comic background (visual V3, split in V4) has its own pins. V4
replaces V3's single combined overlay with the blueprint's pass pair:
the radial action lines pre-render as a transparent layer that main
blits into the world UNDER the entities (the background pass), and the
halftone dot-screen pre-renders as the screen-level print over the
world, under the HUD. The updated pins state the split's rationale
inline — same geometry, same cheap uniform-alpha print, new layering.

The bursts (visual V4) pin the word table by tier, the jagged-star
geometry, the pop-in curve, the alpha-free polygon fade, the
(word, color, size) render cache, the ≤4-text cap with oldest-evicted,
and the real destruction path: POW!/BOOM!/ZAP! join fx ahead of the
debris cloud they sit behind.
"""

import random

import pygame
import pytest

from asteroid import Asteroid
from comicfx import (
    ACTION_LINE_INNER_RADIUS,
    BACKGROUND_ALPHA,
    BURST_LIFETIME_SECONDS,
    BURST_INNER_RATIO,
    BURST_POP_FRACTION,
    BURST_SPIKES,
    BURST_TEXT_MAX_CONCURRENT,
    FRINGE_MAX_PX,
    FRINGE_PX,
    HALFTONE_SPACING,
    Burst,
    build_action_lines,
    build_background_layers,
    build_halftone,
    burst_scale,
    burst_word,
    cached_text,
    chromatic_circle,
    chromatic_polygon,
    clear_burst_texts,
    fade_to_paper,
    jagged_polygon,
    spawn_burst,
)
from constants import (
    ASTEROID_MAX_RADIUS,
    ASTEROID_MIN_RADIUS,
    LINE_WIDTH,
    PALETTE,
    PLAYER_RADIUS,
    POWERUP_SHIELD_RING_GAP,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from main import handle_collisions
from particles import Particle
from player import Player
from powerups import PowerUpType
from shot import Shot

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


# --- Comic background (visual V3/V4): the pass split --------------------------


def test_background_fades_by_uniform_surface_alpha():
    """The halftone print is the measured cheap variant: an opaque surface
    faded by uniform surface alpha. get_alpha() returning the set value is
    the pin — on a per-pixel SRCALPHA surface surface-alpha is unused and
    reads None, and per-pixel blending costs ~0.25ms more per frame for
    nothing."""
    overlay = build_halftone(SCREEN_WIDTH, SCREEN_HEIGHT)
    assert overlay.get_alpha() == BACKGROUND_ALPHA


def test_halftone_carries_the_dot_grid():
    """Dot centers show the halftone swatch with paper between them, and the
    uniform fade lands a blitted dot strictly between the two colors — the
    print screen survives, faded, over whatever the world drew."""
    overlay = build_halftone(SCREEN_WIDTH, SCREEN_HEIGHT)

    dot = (HALFTONE_SPACING, 0)  # a row-0 dot center
    gap = (HALFTONE_SPACING // 2, 0)  # between row-0 dots, clear of row 1
    assert overlay.get_at(dot) == palette_pixel("halftone")
    assert overlay.get_at(gap) == palette_pixel("paper")

    screen = probe_screen()
    screen.blit(overlay, (0, 0))
    faded = screen.get_at(dot)
    assert faded != palette_pixel("paper")  # the dot survives the fade...
    assert faded != palette_pixel("halftone")  # ...but fades toward the paper


def test_action_lines_radiate_and_spare_the_center():
    """The background-pass layer: lines run along the +x ray just past the
    inner radius (opaque pixels on the transparent layer), and the disk
    inside it is fully transparent — the world's paper shows through and
    the play focus at screen center stays clean. (V4 moved this layer from
    the screen-level print into the world, under the entities — same
    geometry, new layering.)"""
    layer = build_action_lines(SCREEN_WIDTH, SCREEN_HEIGHT)
    center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)

    on_ray = [
        layer.get_at((center[0] + offset, center[1]))
        for offset in range(ACTION_LINE_INNER_RADIUS + 2, ACTION_LINE_INNER_RADIUS + 40)
    ]
    assert palette_pixel("action_line") in on_ray

    inner = ACTION_LINE_INNER_RADIUS - 20
    for dx in range(-inner, inner + 1, 4):
        for dy in range(-inner, inner + 1, 4):
            if dx * dx + dy * dy > inner * inner:
                continue  # sample the disk, not the box — corners reach further
            assert layer.get_at((center[0] + dx, center[1] + dy)) == (0, 0, 0, 0)


def test_background_layers_pair_is_lines_then_halftone():
    """build_background_layers hands main the pair in composition order:
    the in-world background pass (a transparent SRCALPHA layer) first, the
    screen-level print (uniform surface alpha) second."""
    lines, halftone = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
    assert lines.get_flags() & pygame.SRCALPHA
    assert halftone.get_alpha() == BACKGROUND_ALPHA


# --- Comic bursts & onomatopoeia (visual V4) ----------------------------------


@pytest.mark.parametrize(
    "radius, word",
    [
        (ASTEROID_MIN_RADIUS, None),         # small: silent — splits never speak
        (ASTEROID_MIN_RADIUS * 2, "BOOM!"),  # medium
        (ASTEROID_MAX_RADIUS, "POW!"),       # large (the field's biggest spawn)
        (ASTEROID_MIN_RADIUS * 4, "POW!"),   # beyond the table: the large band
    ],
)
def test_burst_word_by_tier(radius, word):
    assert burst_word(radius) == word


def test_jagged_polygon_is_a_star_not_a_circle():
    """2*spikes points, the outer reach at the radius and the inner pulled
    in by the ratio — the alternating radii are the jaggedness."""
    points = jagged_polygon(60, rng=random.Random(7))
    assert len(points) == 2 * BURST_SPIKES
    lengths = sorted(point.length() for point in points)
    assert lengths[-1] == pytest.approx(60)
    assert lengths[0] == pytest.approx(60 * BURST_INNER_RATIO)


def test_burst_scale_pops_in_then_holds():
    """Born small, full size by the pop fraction, held there — and never
    past full."""
    assert burst_scale(0.0) == pytest.approx(0.25)
    scales = [burst_scale(fraction / 100) for fraction in range(101)]
    assert scales == sorted(scales)  # monotonic pop-in
    assert burst_scale(BURST_POP_FRACTION) == 1.0
    assert burst_scale(1.0) == 1.0  # held after the pop, never shrinking


def test_fade_to_paper_ends_on_exact_colors():
    """Full color at birth, the paper at death, a blend between — the
    alpha-free fade the opaque world surface needs."""
    assert fade_to_paper((255, 0, 0), 1.0) == (255, 0, 0)
    assert fade_to_paper((255, 0, 0), 0.0) == PALETTE["paper"]
    mid = fade_to_paper((255, 0, 0), 0.5)
    assert PALETTE["paper"][0] < mid[0] < 255


class CountingFont:
    """Delegates render() to a real font while tallying calls — the count
    seam for cache tests. pygame.font.Font is an immutable C type, so its
    render cannot be monkeypatched directly; the cache's font accessor can."""

    def __init__(self, font, calls):
        self._font = font
        self._calls = calls

    def render(self, text, antialias, color=None, background=None):
        self._calls.append(text)
        return self._font.render(text, antialias, color, background)


def test_cached_text_renders_once_per_key(monkeypatch):
    """The (word, color, size) cache: repeat lookups return the same surface
    and never re-render; a new key renders exactly once more. The probe key
    is unique to this test — nothing else renders it."""
    import comicfx

    calls = []
    real = pygame.font.Font(None, 49)
    monkeypatch.setattr(comicfx, "_font", lambda size: CountingFont(real, calls))

    surface = cached_text("CACHE-PROBE", (1, 2, 3), 49)
    assert surface.get_width() > 0
    assert calls == ["CACHE-PROBE"]
    assert cached_text("CACHE-PROBE", (1, 2, 3), 49) is surface  # zero re-renders
    assert calls == ["CACHE-PROBE"]
    cached_text("CACHE-PROBE-2", (1, 2, 3), 49)  # a new key: one more render
    assert calls == ["CACHE-PROBE", "CACHE-PROBE-2"]


def wire_burst_groups():
    """Fresh fx + updatable groups wired to Burst, mirroring main()."""
    fx = pygame.sprite.Group()
    updatable = pygame.sprite.Group()
    Burst.containers = (fx, updatable)
    return fx, updatable


def test_burst_renders_polygon_and_word_headless():
    """A fresh burst lands visible pixels on a paper screen: the spark-fill
    polygon and its ink outline both paint inside its bbox."""
    pygame.init()
    fx, _ = wire_burst_groups()
    burst_fx = Burst(640, 360, 60, "POW!")

    screen = probe_screen()
    burst_fx.draw(screen)

    box = [
        screen.get_at((x, y))
        for x in range(560, 721, 3)
        for y in range(280, 441, 3)
    ]
    assert palette_pixel("spark") in box  # the polygon fill, full color at birth
    assert INK_PIXEL in box  # the inked outline


def test_burst_word_alpha_fades_with_life():
    """The word's surface alpha steps down with the dt-timer — full at
    birth, halved at half-life, the sprite killed exactly at the lifetime.
    The alpha lives on the burst's own rotated copy, never the cache."""
    pygame.init()
    fx, _ = wire_burst_groups()
    burst_fx = Burst(640, 360, 60, "BOOM!")
    screen = probe_screen()

    burst_fx.draw(screen)
    assert burst_fx._text.get_alpha() == 255

    burst_fx.update(BURST_LIFETIME_SECONDS / 2)
    burst_fx.draw(screen)
    assert burst_fx._text.get_alpha() == 127  # int(255 * 0.5)

    burst_fx.update(BURST_LIFETIME_SECONDS / 2)  # the lifetime, spent
    assert not burst_fx.alive()  # killed by the dt-timer


def test_burst_text_cap_evicts_the_oldest():
    """More than 4 concurrent burst texts evict the oldest: the ledger is
    oldest-first, eviction kills (detaching the sprite from fx), and the
    four newest survive."""
    pygame.init()
    clear_burst_texts()
    fx, _ = wire_burst_groups()

    spawned = []
    for i in range(BURST_TEXT_MAX_CONCURRENT + 2):
        spawn_burst(pygame.Vector2(100 + i * 10, 100), 60, "POW!")
        spawned.append(list(fx)[-1])  # the burst just added, in fx order

    assert len(fx) == BURST_TEXT_MAX_CONCURRENT
    assert not spawned[0].alive()  # the two oldest were evicted...
    assert not spawned[1].alive()
    assert all(sprite.alive() for sprite in spawned[2:])  # ...the newest live


def handle_collisions_groups():
    """Fresh groups wired the way main() does, with the V4 fx pass."""
    updatable = pygame.sprite.Group()
    entities = pygame.sprite.Group()
    fx = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    particles = pygame.sprite.Group()
    powerups = pygame.sprite.Group()

    Player.containers = (updatable, entities)
    Asteroid.containers = (asteroids, updatable, entities)
    Shot.containers = (shots, updatable, entities)
    Particle.containers = (particles, updatable, fx)
    Burst.containers = (fx, updatable)
    return asteroids, shots, powerups, fx


def test_destroyed_rock_pops_its_word_behind_the_cloud(tmp_path):
    """The sweep's destruction site: a large rock pops POW!, a medium BOOM!,
    a small nothing — and the burst joins fx AHEAD of the debris, so group
    order draws the polygon behind the particle cloud it salutes."""
    pygame.init()
    for radius, word in (
        (ASTEROID_MAX_RADIUS, "POW!"),
        (ASTEROID_MIN_RADIUS * 2, "BOOM!"),
        (ASTEROID_MIN_RADIUS, None),
    ):
        clear_burst_texts()
        asteroids, shots, powerups, fx = handle_collisions_groups()
        player = Player(100, 660)  # far from the fight: no player hit
        game = Game(player, asteroids, shots, powerups,
                    save_path=tmp_path / "game_save.json")
        Asteroid(640, 360, radius)
        Shot(640, 360)

        handle_collisions(asteroids, shots, player, game, powerups)

        bursts = [sprite for sprite in fx if isinstance(sprite, Burst)]
        clouds = [sprite for sprite in fx if isinstance(sprite, Particle)]
        assert len(bursts) == (0 if word is None else 1)
        if word is not None:
            assert bursts[0].word == word
            assert len(clouds) > 0
            order = fx.sprites()
            assert order.index(bursts[0]) < order.index(clouds[0])  # behind the cloud


def test_player_death_pops_zap(tmp_path):
    """The one place a life is lost pops the death word with the debris —
    ZAP!, through Game.player_hit."""
    pygame.init()
    clear_burst_texts()
    asteroids, shots, powerups, fx = handle_collisions_groups()
    player = Player(100, 660)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    Asteroid(100, 660, 40)  # overlapping the ship

    handle_collisions(asteroids, shots, player, game, powerups)

    bursts = [sprite for sprite in fx if isinstance(sprite, Burst)]
    assert len(bursts) == 1
    assert bursts[0].word == "ZAP!"
