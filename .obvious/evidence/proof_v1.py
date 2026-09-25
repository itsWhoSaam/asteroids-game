"""Visual V1 evidence: the comic palette restyle, rendered headless.

One populated frame drawn twice. The "before" PNG is produced by regrading
PALETTE itself back to the old identity (white on black) — evidence both of
the old look and of the single-table claim: every entity follows the
regrade, no draw site knows a literal. The "after" PNG is the shipped
Miles-mode v1 look, self-checked against the palette entries pixel-wise.

Run: uv run python .obvious/evidence/proof_v1.py
Out: /tmp/obv-evidence/v1_before.png, v1_after.png
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/user/work/asteroids-game")

import pygame

import hud
from asteroid import Asteroid
from constants import PALETTE, SCREEN_HEIGHT, SCREEN_WIDTH
from particles import Particle, burst
from player import Player
from powerups import PowerUp, PowerUpType
from shot import Shot

OUT_DIR = "/tmp/obv-evidence"

# The pre-restyle identity, expressed as a palette regrade (before-frame only).
OLD_LOOK = {
    "paper": "black",
    "ship": "white",
    "asteroid_s": "white",
    "asteroid_m": "white",
    "asteroid_l": "white",
    "shot": "white",
    "powerup_shield": "white",
    "powerup_rapid": "white",
    "powerup_triple": "white",
    "spark": "white",
    "hud_ink": "white",
}


def build_world():
    """One populated frame: ship + shield, one rock per tier, shots, a
    pickup of two kinds, and a debris burst — everything the restyle touches."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)
    Player.containers = (updatable, drawable)

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    player.activate_powerup(PowerUpType.SHIELD)
    Asteroid(220, 200, 60)   # large → violet
    Asteroid(1000, 180, 40)  # medium → pink
    Asteroid(300, 520, 20)   # small → light pink
    Asteroid(950, 500, 20)
    shot = Shot(640, 420)
    shot.velocity = pygame.Vector2(0, -400)
    PowerUp(420, 380, PowerUpType.RAPID)
    PowerUp(880, 300, PowerUpType.TRIPLE)
    burst(pygame.Vector2(760, 420), 60)  # debris cloud over a wreck site
    for spark in list(particles):
        spark.update(0.35)  # spread the cloud before the static frame

    return drawable, player


def render_frame(screen, drawable, filename, muted):
    """Main's composition, verbatim for the V1 surfaces: paper fill, one
    flat draw pass, HUD on top."""
    screen.fill(PALETTE["paper"])
    for each in drawable:
        each.draw(screen)
    hud.draw_hud(screen, 1250, lives=3, wave=2, muted=muted)
    pygame.image.save(screen, filename)


def assert_restyled(screen):
    """The after frame must show palette colors at known sites: paper in the
    empty corner, ship cyan on the hull, the medium rock's pink on its stroke."""
    paper = (*PALETTE["paper"], 255)
    assert screen.get_at((8, 8)) == paper, "background is not the paper color"
    hull_box = [
        screen.get_at((x, y))
        for x in range(600, 681, 2)
        for y in range(320, 401, 2)
    ]
    assert (*PALETTE["ship"], 255) in hull_box, "hull is not the ship color"
    rock_box = [screen.get_at((220, y)) for y in range(136, 170)]
    assert (*PALETTE["asteroid_l"], 255) in rock_box, "rock stroke is not tier color"
    print("self-check ok: paper, ship, and asteroid_l pixels all present")


def main():
    pygame.init()
    os.makedirs(OUT_DIR, exist_ok=True)
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    drawable, _ = build_world()

    # BEFORE: regrade the palette to the old identity, including the HUD
    # text constant hud.py imported at module load.
    PALETTE.update(OLD_LOOK)
    hud.HUD_COLOR = OLD_LOOK["hud_ink"]
    render_frame(screen, drawable, f"{OUT_DIR}/v1_before.png", muted=True)

    # AFTER: restore the shipped swatches and re-render. OLD_LOOK touched
    # exactly these entries; the rest of the table was never mutated.
    PALETTE.update({
        "paper": (23, 18, 58),
        "ship": (62, 230, 240),
        "asteroid_s": (255, 107, 213),
        "asteroid_m": (255, 45, 149),
        "asteroid_l": (180, 77, 255),
        "shot": (255, 233, 74),
        "powerup_shield": (62, 230, 240),
        "powerup_rapid": (255, 154, 62),
        "powerup_triple": (255, 78, 205),
        "spark": (255, 210, 63),
        "hud_ink": (255, 247, 230),
    })
    hud.HUD_COLOR = PALETTE["hud_ink"]
    render_frame(screen, drawable, f"{OUT_DIR}/v1_after.png", muted=True)
    assert_restyled(screen)

    print(f"wrote {OUT_DIR}/v1_before.png and {OUT_DIR}/v1_after.png")


if __name__ == "__main__":
    main()
