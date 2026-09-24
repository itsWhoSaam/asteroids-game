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
"""

import pygame

from constants import PALETTE

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


def build_background(width, height):
    """Pre-render the comic background overlay: paper fill, halftone
    dot-screen, radial action lines — faded and ready to blit every frame.

    Called once at startup (a one-time ~10ms build at 1280x720); the
    per-frame cost is a single opaque set_alpha blit. Deterministic —
    pure arithmetic, no RNG — so tests can probe exact pixels.
    """
    overlay = pygame.Surface((width, height))  # opaque: the cheap variant
    overlay.fill(PALETTE["paper"])  # gaps must blend toward paper, not black
    center = pygame.Vector2(width / 2, height / 2)
    reach = (width**2 + height**2) ** 0.5  # past the farthest corner

    # action lines first — dots are the sharper texture and win overlaps
    line_color = PALETTE["action_line"]
    for i in range(ACTION_LINE_COUNT):
        direction = pygame.Vector2(1, 0).rotate(i * 360 / ACTION_LINE_COUNT)
        start = center + direction * ACTION_LINE_INNER_RADIUS
        end = center + direction * reach
        stroke = 2 if i % 4 == 0 else 1  # every fourth line carries more ink
        pygame.draw.line(overlay, line_color, start, end, stroke)

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
