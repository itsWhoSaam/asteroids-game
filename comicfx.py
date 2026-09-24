"""Chromatic comic outlines (visual V2): entities become inked comic shapes.

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
