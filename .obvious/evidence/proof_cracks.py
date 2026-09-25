"""Chip-damage cracks evidence (Tier 2), headless.

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/ and drives the
real chip path (Asteroid.take_chip) and the real draw path (Asteroid.draw):

- proof_cracks.png          four same-size rocks — untouched and chipped to
                            stages 1-3 — side by side, labeled per stage
- proof_cracks_deepen_a.png one rock after the clicks that first read as
                            stage 1 (3 base clicks on a large rock)
- proof_cracks_deepen_b.png the same rock after 4 more clicks — stage 3
- proof_cracks_after_split.png         the stage-3 rock split through the
                            real death path — both children uncracked

Self-checks: the stage gate reads 0-3 across the strip, interior ink grows
strictly with the stage, the live click sequence steps 1 → 3, and the
post-split children read stage 0 (fresh chip_damage, no carryover).
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from asteroid import Asteroid, crack_stage
from constants import (
    CHIP_CRACK_FRACTIONS,
    CLICK_DAMAGE_BASE,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from hud import points_for

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

PAPER = PALETTE["paper"]
INK = (0, 0, 0)
RADIUS = 40  # a large-ish demo rock; the strip shows one size for comparability

pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))


def font(size):
    f = pygame.font.Font(None, size)
    f.set_bold(True)
    return f


def label(surface, text, center):
    glyph = font(24).render(text, True, PALETTE["hud_ink"])
    surface.blit(glyph, glyph.get_rect(center=center))


def interior_ink(surface, center, radius):
    """Ink pixels strictly inside the hull ring — sampled as a disc of
    0.85·radius around the center, so the chromatic ring (which lives at
    radius + stroke and beyond) can never bleed into the count; only
    crack strokes paint here."""
    cx, cy = int(center.x), int(center.y)
    reach = int(radius * 0.85)
    limit = reach * reach
    return sum(
        1
        for x in range(cx - reach, cx + reach + 1)
        for y in range(cy - reach, cy + reach + 1)
        if (x - cx) ** 2 + (y - cy) ** 2 <= limit
        and surface.get_at((x, y))[:3] == INK
    )


def rock_with_stage(x, y, stage):
    """A rock whose chip damage reads as `stage` — the real draw path."""
    rock = Asteroid(x, y, RADIUS)
    rock.crack_seed = 11  # fixed: reproducible evidence, not a lottery
    if stage > 0:
        rock.chip_damage = CHIP_CRACK_FRACTIONS[stage - 1] * rock.chip_threshold
    return rock


def wire_asteroids():
    """Fresh sprite groups with Asteroid.containers wired, mirroring main() —
    take_chip's alive() gate only answers for rocks that live in a group
    (a bare pygame sprite reports dead), so click-driven sections rewire."""
    updatable, drawable, asteroids = (pygame.sprite.Group() for _ in range(3))
    Asteroid.containers = (asteroids, updatable, drawable)
    return asteroids


# --- the four-stage strip -----------------------------------------------------

CELL = 200
strip = pygame.Surface((4 * CELL, 300))
strip.fill(PAPER)
stages = [0, 1, 2, 3]
ink_counts = []
for i, stage in enumerate(stages):
    center = pygame.Vector2(i * CELL + CELL / 2, 120)
    rock = rock_with_stage(center.x, center.y, stage)
    assert crack_stage(rock.chip_damage, rock.radius) == stage
    rock.draw(strip)  # the real draw path — ring, fringes, and web
    label(strip, f"STAGE {stage}  ({points_for(RADIUS)} pts)", (center.x, 240))
    ink_counts.append(interior_ink(strip, center, RADIUS))

assert ink_counts[0] == 0, "an untouched rock paints no interior ink"
assert ink_counts == sorted(ink_counts), f"cracks must deepen in order: {ink_counts}"
assert len(set(ink_counts[1:])) == 3, f"each stage must read apart: {ink_counts}"
pygame.image.save(strip, f"{OUT}/proof_cracks.png")

# --- live deepening: real clicks, one rock, two frames ------------------------

# A large rock (threshold 9.0): three base clicks read 3/9 — stage 1 — and
# seven read 7/9 — stage 3, still two clicks from the split. (A tier-2 rock
# dies on its sixth click, so its stage-3 window holds exactly one click.)
wire_asteroids()  # alive() needs the rocks in groups for take_chip
deepen = pygame.Surface((CELL, 300))
deepen.fill(PAPER)
rock = Asteroid(CELL / 2, 130, 60)
rock.crack_seed = 11

for _ in range(3):  # 3/9 of the threshold → first hairline pair
    assert rock.take_chip(CLICK_DAMAGE_BASE) is False
assert crack_stage(rock.chip_damage, rock.radius) == 1
rock.draw(deepen)
label(deepen, "3 CLICKS — STAGE 1", (CELL / 2, 240))
frame_a_ink = interior_ink(deepen, rock.position, rock.radius)
pygame.image.save(deepen, f"{OUT}/proof_cracks_deepen_a.png")

for _ in range(4):  # 7/9 → past the 0.75 mark, two clicks from the split
    assert rock.take_chip(CLICK_DAMAGE_BASE) is False
assert crack_stage(rock.chip_damage, rock.radius) == 3
deepen.fill(PAPER)  # fresh paper: frame B must stand alone, not over frame A
rock.draw(deepen)
label(deepen, "7 CLICKS — STAGE 3", (CELL / 2, 240))
frame_b_ink = interior_ink(deepen, rock.position, rock.radius)
pygame.image.save(deepen, f"{OUT}/proof_cracks_deepen_b.png")

assert frame_b_ink > frame_a_ink > 0

# --- split reset: the stage-3 rock dies through the real path -----------------
# Two clean panels — the chipped parent, then the scene after its death:
# the split children on fresh paper, uncracked. Each panel is its own
# surface: drawing both onto one would leave the parent's web showing
# through the hollow children and read as carried-over cracks.
scene = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
scene.fill(PAPER)
panel_w, panel_h = SCREEN_WIDTH // 2, SCREEN_HEIGHT

# Parent panel: a large rock chipped to the last stage, still alive.
parent_panel = pygame.Surface((panel_w, panel_h))
parent_panel.fill(PAPER)
wire_asteroids()  # groups, so the rock is alive for the death that follows
big = Asteroid(panel_w / 2, panel_h / 2, RADIUS * 2)  # threshold 9.0
big.crack_seed = 11
big.chip_damage = big.chip_threshold * 0.8
assert crack_stage(big.chip_damage, big.radius) == 3
big.draw(parent_panel)
label(parent_panel, "PARENT — STAGE 3", (big.position.x, big.position.y + big.radius + 50))
parent_ink = interior_ink(parent_panel, big.position, big.radius)

# Children panel: fresh paper, the real take_chip death, both twins uncracked
# and pulled apart so neither hides the other.
children_panel = pygame.Surface((panel_w, panel_h))
children_panel.fill(PAPER)
asteroids = wire_asteroids()  # fresh group: only the split children land here
big.take_chip(big.chip_threshold)  # the real death: split() through take_chip
assert not big.alive() and len(asteroids) == 2
for child, dx in zip(list(asteroids), (-80, 80)):
    assert child.chip_damage == 0.0
    assert crack_stage(child.chip_damage, child.radius) == 0
    child.crack_seed = 11
    child.position.x = panel_w / 2 + dx
    child.draw(children_panel)
label(
    children_panel,
    "CHILDREN — STAGE 0 (CRACKS RESET)",
    (panel_w / 2, big.position.y + 60 + 50),
)

scene.blit(parent_panel, (0, 0))
scene.blit(children_panel, (panel_w, 0))
pygame.image.save(scene, f"{OUT}/proof_cracks_after_split.png")

assert parent_ink > 0

print("crack evidence OK:")
print(f"  strip interior ink by stage 0..3: {ink_counts}")
print(f"  live deepening 1 → 3: {frame_a_ink} → {frame_b_ink} ink px")
print(f"  split children read stage 0: True")
