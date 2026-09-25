"""Procedural comic FX — no assets, no new dependencies (the sound.py
precedent).

Chromatic comic outlines (visual V2): entities become inked comic shapes.

Every outlined entity renders in three passes, cheapest color last:

1. a thick black ink stroke, `width + FRINGE_PX`, hugging the hull;
2. the chromatic-aberration fringes — the same stroke shifted
   FRINGE_PX left in red and right in cyan;
3. the entity's own color stroke on top.

Pure pygame primitives over palette entries — the sound.py precedent:
no assets, no new dependencies. Particles never route through here:
at burst counts they are the frame's cost driver, so they keep a plain
filled spark with a spawn pop instead (particles.py).

The comic background (visual V3/V4): the radial action lines pre-render
as a transparent layer blitted into the world UNDER the entities (the V4
background pass), and the halftone dot-screen pre-renders as the
screen-level print over the world, under the HUD.

Comic bursts (visual V4): destruction pops a jagged polygon and a rotated
onomatopoeia word — POW!/BOOM!/ZAP! — behind the debris cloud, with text
surfaces cached per (word, color, size) and live words capped.
"""

import random

import pygame

from constants import ASTEROID_MIN_RADIUS, PALETTE

# Halo budget: the ring-band tripwire (the unshielded band 25–32px from
# the ship center must stay paper) leaves ~5px of outline room past the
# hull. The fringes must never poke past the black ink, which holds on
# every call site while FRINGE_PX <= width — both are 2 today. Locked at
# 2 with a hard ceiling of 3 (blueprint).
FRINGE_PX = 2
FRINGE_MAX_PX = 3

INK = (0, 0, 0)

# Left pass bleeds red, right pass bleeds cyan — the chromatic pair.
_FRINGE_PASSES = (
    (-FRINGE_PX, PALETTE["fringe_r"]),
    (FRINGE_PX, PALETTE["fringe_c"]),
)


def chromatic_circle(surface, color, center, radius, width):
    """Inked circle stroke: black outline, offset fringes, colored fill."""
    pygame.draw.circle(surface, INK, center, radius + width, width + FRINGE_PX)
    for dx, fringe in _FRINGE_PASSES:
        pygame.draw.circle(
            surface, fringe, (center[0] + dx, center[1]), radius, width
        )
    pygame.draw.circle(surface, color, center, radius, width)


def chromatic_polygon(surface, color, points, width):
    """Inked polygon stroke (the ship): the same three-pass stack."""
    pygame.draw.polygon(surface, INK, points, width + FRINGE_PX)
    for dx, fringe in _FRINGE_PASSES:
        pygame.draw.polygon(
            surface,
            fringe,
            [(x + dx, y) for (x, y) in points],
            width,
        )
    pygame.draw.polygon(surface, color, points, width)


# --- Comic background (visual V3) -------------------------------------------
# The halftone dot-screen and the radial action lines pre-render ONCE at
# startup into one opaque surface, faded by a uniform surface alpha — the
# measured cheap variant (an opaque + set_alpha blit runs ~1.25ms/frame;
# per-pixel SRCALPHA costs ~0.25ms more and buys nothing at this
# subtlety). The overlay is a screen-level print texture: main blits it
# after the world blit and before the HUD. Entity draw functions never
# paint background, so entity tests keep their black-screen assertions.

# Dot-grid geometry: hex-packed rows (alternate rows offset half a cell)
# read the way print screens do; a plain square grid reads as graph paper.
HALFTONE_SPACING = 12
HALFTONE_DOT_RADIUS = 2

# Radial action lines emanate from this radius outward — the play focus at
# screen center stays clean — at even angle steps around the clock.
ACTION_LINE_COUNT = 24
ACTION_LINE_INNER_RADIUS = 150

# Uniform fade of the whole overlay. 56/255 ≈ 22%: dots and lines sit
# faintly over the paper and dim bright entities the way newsprint does.
BACKGROUND_ALPHA = 56

# --- Comic bursts & onomatopoeia (visual V4) --------------------------------
# Destruction speaks: a jagged burst polygon pops behind the debris cloud
# with a rotated word stamped on it. Every number here is a tunable, same
# as the V3 block above; the words are content, so they live beside them.

# The word table, by destruction kind: large rocks POW!, medium BOOM!,
# small rocks stay silent (they die constantly — a word on every split
# would drown the field), and the player's death ZAP!s.
BURST_WORD_LARGE = "POW!"
BURST_WORD_MEDIUM = "BOOM!"
BURST_WORD_DEATH = "ZAP!"

BURST_LIFETIME_SECONDS = 0.8      # whole pop-in + fade cycle
BURST_POP_FRACTION = 0.25         # first quarter of life is the pop-in
BURST_SPIKES = 12                 # jagged star points (outer + inner per spike)
BURST_INNER_RATIO = 0.55          # inner radius as a fraction of outer — jaggedness
BURST_JITTER_DEGREES = 10.0       # per-spike angle jitter — jagged, never tangled
BURST_PAD_PX = 8                  # polygon reach past the destroyed body's radius
BURST_OUTLINE_PX = 2              # ink stroke around the burst polygon
BURST_TEXT_FONT_SIZE = 48
BURST_TEXT_TILT_DEGREES = 15.0    # random tilt band — comic lettering, never upside-down
BURST_TEXT_MAX_CONCURRENT = 4     # cap on live burst texts; the oldest is evicted


def build_action_lines(width, height):
    """Pre-render the radial action lines as a transparent layer (visual
    V4): main blits it into the world as the background pass — UNDER the
    entities, so the lines sit behind the rocks they speed past (the
    blueprint's pass split) instead of tinting them from screen level as
    the combined V3 overlay did. Deterministic — pure arithmetic, no RNG.

    Called once at startup; the per-frame cost is one full-screen
    SRCALPHA blit (~1.5ms measured, inside the 12ms composite budget).
    """
    layer = pygame.Surface((width, height), pygame.SRCALPHA)
    center = pygame.Vector2(width / 2, height / 2)
    reach = (width**2 + height**2) ** 0.5  # past the farthest corner

    line_color = PALETTE["action_line"]
    for i in range(ACTION_LINE_COUNT):
        direction = pygame.Vector2(1, 0).rotate(i * 360 / ACTION_LINE_COUNT)
        start = center + direction * ACTION_LINE_INNER_RADIUS
        end = center + direction * reach
        stroke = 2 if i % 4 == 0 else 1  # every fourth line carries more ink
        pygame.draw.line(layer, line_color, start, end, stroke)

    return layer


def build_halftone(width, height):
    """Pre-render the halftone dot-screen as the screen-level print (visual
    V4): paper fill + dots, opaque and faded by uniform surface alpha — the
    measured cheap variant. Blitted over the shaken world and under the
    HUD, exactly where the combined V3 overlay sat. Deterministic.
    """
    overlay = pygame.Surface((width, height))  # opaque: the cheap variant
    overlay.fill(PALETTE["paper"])  # gaps must blend toward paper, not black

    # hex-packed dot grid: alternate rows offset half a cell
    dot_color = PALETTE["halftone"]
    rows = height // HALFTONE_SPACING + 1
    cols = width // HALFTONE_SPACING + 1
    for row in range(rows):
        y = row * HALFTONE_SPACING
        x_offset = (row % 2) * HALFTONE_SPACING / 2
        for col in range(cols):
            pygame.draw.circle(
                overlay, dot_color, (col * HALFTONE_SPACING + x_offset, y),
                HALFTONE_DOT_RADIUS,
            )

    overlay.set_alpha(BACKGROUND_ALPHA)
    return overlay


def build_background_layers(width, height):
    """The comic background pair, built once at startup: (action-lines
    layer, halftone overlay). Main composes the lines into the world as
    the background pass and prints the dot-screen at screen level — the
    V4 pass split replaces V3's single combined overlay."""
    return build_action_lines(width, height), build_halftone(width, height)


# --- Comic bursts & onomatopoeia (visual V4) ---------------------------------


def burst_word(radius):
    """Pure word selection for a destroyed body: POW! on the large tier,
    BOOM! on medium, None on small — small rocks die constantly, and a
    word on every split would drown the field. Tiers follow points_for's
    bands (multiples of ASTEROID_MIN_RADIUS)."""
    if radius >= ASTEROID_MIN_RADIUS * 3:
        return BURST_WORD_LARGE
    if radius >= ASTEROID_MIN_RADIUS * 2:
        return BURST_WORD_MEDIUM
    return None


def jagged_polygon(radius, rng=random):
    """Pure burst-star geometry: BURST_SPIKES outer/inner point pairs
    alternating around the clock, each pair jittered so no two bursts read
    identical. Points are relative to the burst center, ready to scale and
    offset at draw time."""
    step = 360 / BURST_SPIKES
    points = []
    for i in range(BURST_SPIKES):
        outer_angle = i * step + rng.uniform(-BURST_JITTER_DEGREES, BURST_JITTER_DEGREES)
        points.append(pygame.Vector2(1, 0).rotate(outer_angle) * radius)
        inner_angle = outer_angle + step / 2
        points.append(
            pygame.Vector2(1, 0).rotate(inner_angle) * radius * BURST_INNER_RATIO
        )
    return points


def burst_scale(progress):
    """Pure pop-in curve: born at a quarter size, full by BURST_POP_FRACTION
    of the lifetime, held there — the burst pops, it doesn't grow forever."""
    if progress >= BURST_POP_FRACTION:
        return 1.0
    return 0.25 + 0.75 * (progress / BURST_POP_FRACTION)


def fade_to_paper(color, life_fraction):
    """Pure alpha-free fade: lerp a color toward the paper as the burst's
    life burns. The world surface is opaque, so per-pixel alpha is off the
    table (the house no-alpha-fade pattern, particles.py) — the lerp is it."""
    paper = PALETTE["paper"]
    return tuple(int(round(p + (c - p) * life_fraction)) for c, p in zip(color, paper))


# Text surfaces are cached per (word, color, size): one font.render per key
# for the process lifetime. The survey's flagged hot path was a render per
# frame per sprite — nothing here may repeat that pattern.
_text_fonts = {}
_text_cache = {}


def _font(size):
    font = _text_fonts.get(size)
    if font is None:
        font = pygame.font.Font(None, size)
        _text_fonts[size] = font
    return font


def cached_text(word, color, size):
    """A rendered text surface, shared per (word, color, size).

    Cache entries are borrowed, never mutated: anything that needs
    per-frame alpha keeps its own copy (Burst rotates one at spawn; the
    wave banner renders its own). Consumers: burst words and the pickup
    letters — one render per key instead of one per frame per pickup."""
    key = (word, color, size)
    surface = _text_cache.get(key)
    if surface is None:
        surface = _font(size).render(word, True, color)
        _text_cache[key] = surface
    return surface


# Live burst texts, oldest first — the cap's ledger. Only live sprites are
# in it: every exit path funnels through Burst.kill, which deregisters.
_live_burst_texts = []


def clear_burst_texts():
    """Drop the ledger (test isolation; no run-state depends on it)."""
    _live_burst_texts.clear()


def evict_oldest_burst_texts(limit=BURST_TEXT_MAX_CONCURRENT):
    """Cap the ledger: kill the oldest bursts beyond `limit`. kill()
    deregisters, so eviction and natural death share one exit."""
    while len(_live_burst_texts) > limit:
        _live_burst_texts[0].kill()


def spawn_burst(position, body_radius, word):
    """One comic burst at a death site: the jagged polygon sized to the
    body plus its rotated word. The call site spawns this BEFORE the
    particle burst — joining fx first puts the polygon behind the cloud
    it salutes (group order is insertion order)."""
    Burst(position.x, position.y, body_radius, word)
    evict_oldest_burst_texts()


class Burst(pygame.sprite.Sprite):
    """The onomatopoeia burst: jagged polygon with a rotated word on it,
    one lifecycle. Pops in over the first fraction of its life, then fades
    — the polygon by color-lerp toward the paper (the world is opaque, no
    alpha), the word by surface alpha on its own rotated copy (per-frame
    set_alpha composes with the antialiased glyph alpha on pygame 2.6.1,
    probe-verified). Joins its containers like every sprite; main wires it
    to fx + updatable."""

    containers = ()

    def __init__(self, x, y, body_radius, word, color=None):
        if self.containers:
            super().__init__(self.containers)
        else:
            super().__init__()
        self.position = pygame.Vector2(x, y)
        self.word = word
        self.color = PALETTE["spark"] if color is None else color
        self.lifetime = BURST_LIFETIME_SECONDS
        self.age = 0.0
        self.radius = body_radius + BURST_PAD_PX
        self._polygon = jagged_polygon(self.radius)
        tilt = random.uniform(-BURST_TEXT_TILT_DEGREES, BURST_TEXT_TILT_DEGREES)
        # One rotate at spawn, off the shared cache — never per frame.
        self._text = pygame.transform.rotate(
            cached_text(word, self.color, BURST_TEXT_FONT_SIZE), tilt
        )
        _live_burst_texts.append(self)

    def update(self, dt):
        self.age += dt
        if self.age >= self.lifetime:
            self.kill()

    def kill(self):
        super().kill()
        if self in _live_burst_texts:
            _live_burst_texts.remove(self)

    def draw(self, surface):
        progress = self.age / self.lifetime
        life_fraction = 1.0 - progress
        scale = burst_scale(progress)
        points = [
            (self.position.x + point.x * scale, self.position.y + point.y * scale)
            for point in self._polygon
        ]
        # Filled star, inked outline — both fade toward the paper.
        pygame.draw.polygon(surface, fade_to_paper(self.color, life_fraction), points)
        pygame.draw.polygon(
            surface, fade_to_paper(INK, life_fraction), points, BURST_OUTLINE_PX
        )
        self._text.set_alpha(int(255 * life_fraction))
        surface.blit(self._text, self._text.get_rect(center=self.position))
