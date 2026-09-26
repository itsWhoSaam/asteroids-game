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

Comic HUD panels (visual V5): build_panel() pre-renders the yellow
halftone plates with black ink borders that the HUD, the game-over
overlay, and the wave banner sit on, and cached_rotated_text() extends
the render cache with rotated copies (the banner's per-letter tilt) —
still one render per key, never per frame. The shared fonts render
BOLD: comic lettering is the point, and one flag at font creation keeps
every cache entry's metrics consistent.
"""

import math
import random

import pygame

from constants import (
    ASTEROID_MIN_RADIUS,
    CHIP_CRACK_FRACTIONS,
    CRATER_COUNT,
    CRATER_RADIUS_FRACTION,
    PALETTE,
    SILHOUETTE_JITTER,
    SILHOUETTE_LIGHT_ANGLE,
    SILHOUETTE_SHADOW_DEPTH,
    SILHOUETTE_VERTICES,
    ASTEROID_SPIN_MAX_DPS,
    ASTEROID_SPIN_MIN_DPS,
)

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
        font.set_bold(True)  # comic lettering (V5) — set once, at creation
        _text_fonts[size] = font
    return font


def shared_font(size):
    """The shared bold font for a size — the accessor hud.py's font
    helpers delegate to, so ad-hoc renders (test rect math) measure the
    same glyphs the cache produces."""
    return _font(size)


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


# --- Comic HUD panels (visual V5) ---------------------------------------------
# The yellow halftone plates with black ink borders that the HUD, the
# game-over overlay, and the wave banner sit on. Pre-rendered like the
# background: build once per size, blit forever — never drawn with
# primitives per frame.

PANEL_DOT_SPACING = 10  # px between halftone dots on a panel
PANEL_DOT_RADIUS = 2
PANEL_BORDER_PX = 3     # the ink border stroke


def build_panel(width, height):
    """Pre-render one comic panel: yellow plate, darker halftone dots, black
    ink border. Opaque — blitting it is the cheap full-color case, and a
    uniform surface alpha (the halftone print's mechanism) fades it cleanly.

    Deterministic — pure arithmetic, no RNG, so every panel of a size is
    pixel-identical (tests may assert against its colors)."""
    panel = pygame.Surface((width, height))
    panel.fill(PALETTE["hud_panel"])

    # hex-packed dot grid, same geometry family as the screen halftone
    dot_color = PALETTE["hud_panel_dot"]
    rows = height // PANEL_DOT_SPACING + 1
    cols = width // PANEL_DOT_SPACING + 1
    for row in range(rows):
        y = PANEL_BORDER_PX + row * PANEL_DOT_SPACING
        x_offset = (row % 2) * PANEL_DOT_SPACING / 2
        for col in range(cols):
            x = PANEL_BORDER_PX + col * PANEL_DOT_SPACING + x_offset
            if x > width - PANEL_BORDER_PX or y > height - PANEL_BORDER_PX:
                continue  # dots stay inside the ink border
            pygame.draw.circle(panel, dot_color, (x, y), PANEL_DOT_RADIUS)

    pygame.draw.rect(panel, INK, panel.get_rect(), PANEL_BORDER_PX)
    return panel


_rotated_cache = {}


def cached_rotated_text(text, color, size, angle):
    """One rotated glyph, cached per (text, color, size, angle) — the wave
    banner's letter path.

    The color may carry a per-frame alpha (the fade parameter):
    pygame's font render ignores a color's alpha channel, so the band's
    alpha is scaled into the glyph's antialias coverage with a
    BLEND_RGBA_MULT fill on the rotated copy — per-pixel alpha without
    surface set_alpha (which does not compose with SRCALPHA) and without
    re-rendering text per frame. The full-ink base glyph comes from the
    shared text cache; band surfaces are per-key and never shared."""
    if angle == 0:
        return cached_text(text, color, size)
    key = (text, color, size, angle)
    surface = _rotated_cache.get(key)
    if surface is None:
        base = cached_text(text, color[:3], size)
        surface = pygame.transform.rotate(base, angle)
        if len(color) > 3 and color[3] < 255:
            surface.fill(
                (255, 255, 255, color[3]),
                special_flags=pygame.BLEND_RGBA_MULT,
            )
        _rotated_cache[key] = surface
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


# --- Chip-damage cracks (Tier 2) ---------------------------------------------
# Idle-clicked rocks crack: an ink web over the hull that deepens with the
# chip stage. The geometry is pure and deterministic per (radius, seed) —
# re-seeded on every call, so a drifting rock's cracks stick to its body
# frame to frame — and the full stage-3 web is generated whole and revealed
# as a prefix, so deepening shows more of the same web instead of redrawing
# a new one. Plain draw.lines strokes on the world surface — no surfaces,
# no alpha, the headless dummy-driver contract.

CRACK_LINES_PER_STAGE = 2    # new ink lines each stage reveals
CRACK_INNER_FRACTION = 0.2   # cracks start off-center, not at the exact middle
CRACK_MID_FRACTION = 0.55    # the jag's midpoint radius
CRACK_REACH_FRACTION = 0.9   # deepest reach, as a fraction of the hull radius
CRACK_JITTER_DEGREES = 16.0  # per-vertex angular jitter — jagged, not spokes
CRACK_WIDTHS = (1, 2, 2)     # stroke width by stage: hairline first, ink after


def crack_polylines(radius, seed):
    """Pure crack geometry for a chipped rock: the full stage-3 web of
    jagged ink polylines, relative to the rock's center. The web a rock
    grows into is fixed at birth by its seed, and stage n reveals the
    first n * CRACK_LINES_PER_STAGE polylines of it — the pattern never
    jumps as the damage deepens, it just gains lines."""
    rng = random.Random(seed)
    count = CRACK_LINES_PER_STAGE * len(CHIP_CRACK_FRACTIONS)
    web = []
    for i in range(count):
        heading = i * 360 / count + rng.uniform(-CRACK_JITTER_DEGREES, CRACK_JITTER_DEGREES)
        mid = heading + rng.uniform(-CRACK_JITTER_DEGREES, CRACK_JITTER_DEGREES)
        web.append([
            pygame.Vector2(1, 0).rotate(heading) * radius * CRACK_INNER_FRACTION,
            pygame.Vector2(1, 0).rotate(mid) * radius * CRACK_MID_FRACTION,
            pygame.Vector2(1, 0).rotate(heading) * radius * CRACK_REACH_FRACTION,
        ])
    return web


def draw_cracks(surface, center, radius, stage, seed, angle=0.0):
    """The ink crack web over a chipped rock, deepening with the stage:
    stage n draws the first n * CRACK_LINES_PER_STAGE polylines of the
    rock's seeded web, stroked wider as the cracks deepen. Pure ink lines
    on the opaque world surface — never per-pixel alpha.

    angle: the body's spin in degrees (semi-3D) — the web sticks to the
    rock's frame, so it tumbles with the hull. The default keeps the
    angle-free call sites and their pins identical."""
    if stage <= 0:
        return
    stage = min(stage, len(CHIP_CRACK_FRACTIONS))
    width = CRACK_WIDTHS[min(stage, len(CRACK_WIDTHS)) - 1]
    for polyline in crack_polylines(radius, seed)[: stage * CRACK_LINES_PER_STAGE]:
        pygame.draw.lines(
            surface,
            INK,
            False,
            [
                (center[0] + point.rotate(angle).x, center[1] + point.rotate(angle).y)
                for point in polyline
            ],
            width,
        )


# --- Semi-3D rocks & ship (ship-and-rock shading PR) --------------------------
# Presentation-only pseudo-3D: pure geometry helpers plus the one-time rock
# bake. Per-frame draw cost stays blit + polygon strokes — the V3/V4 budget
# contract — and every color site resolves through PALETTE upstream.

# The shape streams are deliberately one-per-aspect: silhouette, craters, and
# spin each reseed their own random.Random off the rock's one shape seed, so
# adding an aspect later cannot reshuffle the others.


def mix_colors(a, b, t):
    """Pure color lerp a→b at fraction t — fade_to_paper generalized to any
    pair of palette entries (the no-alpha-fade house pattern)."""
    return tuple(int(round(c_a + (c_b - c_a) * t)) for c_a, c_b in zip(a, b))


def light_direction():
    """The shared light's screen direction: up-left, the heading the rock
    bakes and the ship's canopy glint both read. A Vector2 so callers can
    scale it straight into an offset."""
    return pygame.Vector2(1, 0).rotate(SILHOUETTE_LIGHT_ANGLE)


def silhouette_points(radius, seed):
    """Seeded lumpy silhouette (semi-3D): SILHOUETTE_VERTICES vertices at
    even angle steps, each radius jittered within ±SILHOUETTE_JITTER of the
    hull radius. Points are relative to the rock center, in draw order —
    ready for draw.polygon's smooth-closed path.

    Deterministic per (radius, seed): the seed is fixed at birth (the
    crack_seed precedent), so a drifting rock keeps its shape and split
    children draw their own. The web twin derives the same shape from the
    rock's snapshot id — no protocol change."""
    rng = random.Random(seed)
    vertex_lo, vertex_hi = SILHOUETTE_VERTICES
    jitter_lo, jitter_hi = SILHOUETTE_JITTER
    count = rng.randint(vertex_lo, vertex_hi)
    points = []
    for i in range(count):
        heading = i * 360 / count
        jitter = rng.uniform(jitter_lo, jitter_hi) * rng.choice((-1, 1))
        points.append(
            pygame.Vector2(1, 0).rotate(heading) * radius * (1 + jitter)
        )
    return points


def crater_specs(radius, seed):
    """Seeded crater layout (semi-3D): 2–5 ellipses per rock, each a
    (center offset, rx, ry) tuple relative to the rock center. Centers stay
    well inside the hull, so a crater and its lit rim never cross the
    silhouette even at the deepest silhouette dip."""
    rng = random.Random(seed + 1)  # a stream apart from the silhouette's
    count_lo, count_hi = CRATER_COUNT
    radius_lo, radius_hi = CRATER_RADIUS_FRACTION
    craters = []
    for _ in range(rng.randint(count_lo, count_hi)):
        offset = (
            pygame.Vector2(1, 0).rotate(rng.uniform(0, 360))
            * rng.uniform(0, 0.62)
            * radius
        )
        rx = rng.uniform(radius_lo, radius_hi) * radius
        ry = rx * rng.uniform(0.65, 0.95)
        craters.append((offset, rx, ry))
    return craters


def spin_rate_for(seed):
    """Seeded signed spin rate in deg/s (semi-3D tumble): magnitude inside
    the ASTEROID_SPIN band, direction a coin flip — presentation-only state
    the sim never reads."""
    rng = random.Random(seed + 2)  # a stream apart from the shape's
    rate = rng.uniform(ASTEROID_SPIN_MIN_DPS, ASTEROID_SPIN_MAX_DPS)
    return rate if rng.random() < 0.5 else -rate


def bake_rock_surface(
    radius, seed, tier_color=None, shadow_color=None, highlight_color=None,
    flat_color=None,
):
    """Pre-render a rock's shaded body (semi-3D): the silhouette filled with
    the tier hue, a hard two-band shadow crescent at the rim the light
    misses, the warm highlight arc on the lit side, and the seeded craters
    beneath the crack web. SRCALPHA — opaque inside the silhouette,
    transparent outside — so the per-frame cost is one rotate + blit, and
    the ink stack traces the silhouette on top at draw time.

    flat_color (the mine's dark hull): a variant's flat fill — silhouette
    only, no shading, craters, or arc, so the variant keeps its flat menace.

    The light is baked in the body's local frame (the spec's bake-and-rotate
    design): at spin 0 it shines from up-left on screen, and the bake
    tumbles with the rock thereafter."""
    pad = 4  # room for the lumpiest vertex past the nominal radius
    size = int(radius * 2) + pad * 2
    bake = pygame.Surface((size, size), pygame.SRCALPHA)
    center = pygame.Vector2(size / 2, size / 2)
    silhouette = silhouette_points(radius, seed)
    outer = [(center.x + v.x, center.y + v.y) for v in silhouette]

    if flat_color is not None:
        pygame.draw.polygon(bake, flat_color, outer)
        return bake

    # Two-band cel shading: the tier hue fills the body, then the shadow
    # crescent paints between the silhouette and the lit polygon — each lit
    # vertex pulled radially in by the depth the light misses at its angle
    # (deepest on the anti-light rim, tapering to zero on the lit side).
    # Hard band edges — cel-shaded, no airbrushing (the locked style).
    pygame.draw.polygon(bake, tier_color, outer)
    anti_light = SILHOUETTE_LIGHT_ANGLE + 180.0
    inner = []
    for v in silhouette:
        heading = math.degrees(math.atan2(v.y, v.x))
        depth = SILHOUETTE_SHADOW_DEPTH * radius * max(
            0.0, math.cos(math.radians(heading - anti_light))
        )
        lit = v - v.normalize() * depth
        inner.append((center.x + lit.x, center.y + lit.y))
    pygame.draw.polygon(bake, shadow_color, outer + inner[::-1])

    # The single warm highlight arc on the lit side, inset from the edge.
    arc_radius = radius * 0.62
    arc = []
    for step in range(-4, 5):
        heading = math.radians(SILHOUETTE_LIGHT_ANGLE + step * 15.0)
        arc.append((
            center.x + math.cos(heading) * arc_radius,
            center.y + math.sin(heading) * arc_radius,
        ))
    pygame.draw.lines(bake, highlight_color, False, arc, 3)

    # Seeded craters: dark bowls with a lit rim glint on the light-facing
    # edge — surface detail over the shading, beneath the crack web.
    for offset, rx, ry in crater_specs(radius, seed):
        bowl_center = center + offset
        bowl = pygame.Rect(0, 0, int(rx * 2), int(ry * 2))
        bowl.center = (int(bowl_center.x), int(bowl_center.y))
        pygame.draw.ellipse(bake, shadow_color, bowl)
        rim = []
        for step in range(-2, 3):
            heading = math.radians(SILHOUETTE_LIGHT_ANGLE + step * 30.0)
            rim.append((
                bowl_center.x + math.cos(heading) * rx * 0.85,
                bowl_center.y + math.sin(heading) * ry * 0.85,
            ))
        pygame.draw.lines(bake, highlight_color, False, rim, 2)

    return bake


def hull_gradient_bands(nose, tail_a, tail_b, bands):
    """Pure band geometry for the ship's nose→tail hull gradient: the
    triangle tiled into `bands` quads between the tail edge and the nose
    vertex, each as (quad_points, band_fraction 0=tail..1=nose) so the
    caller maps fractions to its own color pair. Hard band edges — the cel
    style the rocks share."""
    out = []
    for i in range(bands):
        t0, t1 = i / bands, (i + 1) / bands
        a0, a1 = tail_a.lerp(nose, t0), tail_a.lerp(nose, t1)
        b0, b1 = tail_b.lerp(nose, t0), tail_b.lerp(nose, t1)
        quad = [(a0.x, a0.y), (a1.x, a1.y), (b1.x, b1.y), (b0.x, b0.y)]
        out.append((quad, (t0 + t1) / 2))
    return out


def ellipse_points(center, rx, ry, angle_degrees, segments=12):
    """Pure rotated-ellipse outline points — pygame.draw.ellipse is
    axis-aligned only, and the ship's canopy must bank and turn with the
    hull. Closed-ready for draw.polygon."""
    points = []
    for i in range(segments):
        t = math.radians(i * 360 / segments)
        point = pygame.Vector2(math.cos(t) * rx, math.sin(t) * ry)
        point = point.rotate(angle_degrees)
        points.append((center.x + point.x, center.y + point.y))
    return points
