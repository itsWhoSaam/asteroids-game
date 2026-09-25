"""The V4 composition contract: main's render_world draws three explicit
passes into the world — background (static action lines), entities, fx —
then blits the world at the shake offset, prints the halftone overlay at
screen level, and renders the HUD last, unshaken.

These tests pin the blueprint's pass split as pixels and order:

- fx always lands above entities at any overlap (particles and burst
  texts decorate the field; they never hide behind rocks);
- the action-line layer sits UNDER entities (a background pass, never a
  screen-level wash over the field);
- the halftone print dims the composed world (screen-level, over the
  world blit) — so overlap assertions read channel balance, not exact
  colors: the print multiplies every world pixel by ~78%;
- the HUD renders last: exact ink pixels at the absolute top-left slot
  even while the world blits at a real shake offset — the HUD draws
  after the print, so its glyphs are not dimmed.

Also here: the text-cache discipline — with pickups, the wave banner,
the HUD, and the game-over overlay visible across simulated frames,
font render calls go flat after the first frame (the survey's flagged
per-frame allocation pattern, dead since V4 for burst words and pickup
letters; V5 routes HUD, overlay, and banner text through the same
cache, so the loop now covers every text draw).
"""

import pygame

import comicfx
from comicfx import (
    ACTION_LINE_INNER_RADIUS,
    BURST_WORD_MEDIUM,
    Burst,
    build_background_layers,
)
from constants import (
    HUD_MARGIN,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from hud import WaveBanner, draw_game_over, draw_hud
from main import render_world
from powerups import PowerUp, PowerUpType

ENTITY_RED = (255, 0, 0)
FX_GREEN = (0, 255, 0)


class Blob(pygame.sprite.Sprite):
    """A house-style draw() probe: an opaque disk that paints its color at
    its position — the minimal thing a draw pass can render."""

    def __init__(self, position, color, containers):
        super().__init__(containers)
        self.position = pygame.Vector2(position)
        self.color = color
        self.radius = 12

    def draw(self, surface):
        pygame.draw.circle(surface, self.color, self.position, self.radius)


class FakeGame:
    """The run-state slice render_world reads for the HUD."""

    score = 77
    lives = 3
    wave = 2
    muted = False


class CountingFont:
    """Delegates render() to a real font while tallying calls — the count
    seam for the flat-cache test (pygame.font.Font is an immutable C type,
    so its render cannot be monkeypatched directly; the accessors can)."""

    def __init__(self, font, calls):
        self._font = font
        self._calls = calls

    def render(self, text, antialias, color=None, background=None):
        self._calls.append(text)
        return self._font.render(text, antialias, color, background)

    def size(self, text):
        return self._font.size(text)  # layout metrics pass through, uncounted

    def get_height(self):
        return self._font.get_height()


def compose(entities=None, fx=None, offset=(0, 0)):
    """Run render_world on fresh surfaces with the real background pair."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    world = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    background = build_background_layers(SCREEN_WIDTH, SCREEN_HEIGHT)
    render_world(screen, world, background, entities or pygame.sprite.Group(),
                 fx or pygame.sprite.Group(), offset, FakeGame())
    return screen


def test_fx_pass_renders_after_the_entity_pass():
    """An fx blob and an entity blob at the same spot: the fx color wins
    the overlap — particles and bursts always land above the field. The
    halftone print dims the winner ~22%, so the assertion reads channel
    balance: green dominant means fx drew last; red dominant would mean
    the entity pass ran after fx."""
    entities = pygame.sprite.Group()
    fx = pygame.sprite.Group()
    Blob((400, 400), ENTITY_RED, entities)
    Blob((400, 400), FX_GREEN, fx)

    screen = compose(entities, fx)

    overlap = screen.get_at((400, 400))
    assert overlap.g > 200 and overlap.r < 40 and overlap.b < 40


def test_background_pass_renders_under_entities():
    """The action-line layer is pass 1: an entity sitting on a line point
    paints over it — background never covers the field. A nearby line
    pixel still shows (dimmed by the print) where nothing covers it."""
    entities = pygame.sprite.Group()
    center_x = SCREEN_WIDTH // 2
    center_y = SCREEN_HEIGHT // 2
    Blob((center_x + ACTION_LINE_INNER_RADIUS + 10, center_y), ENTITY_RED,
         entities)

    screen = compose(entities)

    covered = screen.get_at((center_x + ACTION_LINE_INNER_RADIUS + 10, center_y))
    # the entity wins the line point — red dominant — dimmed by the print
    assert covered.r > 150 and covered.g < 40 and covered.b < 40
    open_line = screen.get_at((center_x + ACTION_LINE_INNER_RADIUS + 30, center_y))
    # the line still shows where nothing covers it — not paper, not the blob
    assert open_line != (*PALETTE["paper"], 255)
    assert open_line.r < 100


def test_halftone_print_lands_over_the_world():
    """The screen-level print dims the composed world: a halftone dot over
    an entity's pixels fades them — the print sits over everything drawn
    into the world and under the HUD. The probe sits at the same dot row
    as the original (18, 12) point but clear of the V5 HUD panel, which
    now covers the top-left corner the old probe shared."""
    entities = pygame.sprite.Group()
    Blob((606, 12), ENTITY_RED, entities)  # a row-1 halftone dot center

    screen = compose(entities)

    dotted = screen.get_at((606, 12))
    assert dotted != (*ENTITY_RED, 255)  # the dot screen dimmed the entity...

    # ...and each channel of the mix sits between the entity color and the
    # halftone swatch it was faded toward — a real blend, not a cover-up
    for lo, hi, seen in zip(ENTITY_RED, PALETTE["halftone"], dotted[:3]):
        low, high = sorted((lo, hi))
        assert low <= seen <= high


def test_hud_renders_last_and_unshaken():
    """With the world blitted at a real shake offset, HUD text keeps exact
    ink pixels at the absolute top-left slot — drawn after the halftone
    print, above everything, and never displaced by the shake (F5)."""
    entities = pygame.sprite.Group()
    Blob((400, 400), ENTITY_RED, entities)

    screen = compose(entities, offset=(7, 3))

    # the entity moved with the world blit...
    moved = screen.get_at((407, 403))
    assert moved.r > 150 and moved.g < 40  # red dominant, print-dimmed
    # ...the HUD did not: an exact hud_ink pixel in the score slot — the
    # HUD draws after the print, so its glyphs keep their exact color
    samples = [
        screen.get_at((x, y))
        for x in range(HUD_MARGIN, HUD_MARGIN + 140)
        for y in range(HUD_MARGIN, HUD_MARGIN + 30)
    ]
    assert (*PALETTE["hud_ink"], 255) in samples


def test_font_render_calls_stay_flat_across_frames(monkeypatch):
    """The cache discipline, simulated: with three pickups, the wave
    banner, a burst, the HUD, and the game-over overlay visible, frame 1
    fills the shared caches and every later frame renders ZERO new text
    surfaces — counted at comicfx._font, the one font seam every text
draw shares (V5 moved the banner off its own per-wave render and the
HUD off raw renders onto the cache)."""
    pygame.init()
    calls = []

    fonts = {}

    def counting_font(size):
        real = fonts.setdefault(size, pygame.font.Font(None, size))
        return CountingFont(real, calls)

    monkeypatch.setattr(comicfx, "_font", counting_font)

    # The draws under test, wired to no groups — main's group split is
    # composition-tested above; this loop isolates the allocation pattern.
    Burst.containers = ()
    burst = Burst(400, 300, 60, BURST_WORD_MEDIUM)
    banner = WaveBanner()
    banner.show(2)
    PowerUp.containers = ()
    pickups = [
        PowerUp(200 + i * 100, 200, kind)
        for i, kind in enumerate(
            (PowerUpType.SHIELD, PowerUpType.RAPID, PowerUpType.TRIPLE,
             PowerUpType.MAGNET)
        )
    ]

    counts = []
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    for _ in range(10):  # the banner and burst both outlive the window
        burst.update(1 / 60)
        banner.update(1 / 60)
        for pickup in pickups:
            pickup.update(1 / 60)
        burst.draw(screen)
        banner.draw(screen)
        for pickup in pickups:
            pickup.draw(screen)
        draw_hud(screen, 77, lives=3, wave=2)
        draw_game_over(screen, 77, new_high=True)
        counts.append(len(calls))

    assert counts[0] > 0  # the first frame fills the caches (letters, word, HUD)
    assert counts[1:] == [counts[0]] * (len(counts) - 1)  # then: dead flat
