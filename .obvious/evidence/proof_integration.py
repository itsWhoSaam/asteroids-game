"""Integration-pass evidence: shop panel + active powerup state, headless.

Follows the proof.py pattern — a bounded scripted session under SDL dummy
drivers that saves PNG screenshots to /tmp/obv-evidence/. The scenario is
the balance harness's own world (tests/_balance_sim.py): a few simulated
seconds of shooting, clicking, buying, and drones, rendered exactly like
main()'s render block:

- integration_shop_panel.png    the bottom shop panel with live costs and
                                affordability colors, credits HUD, drones
- integration_powerup_active.png after one Overdrive + one Gold Rush
                                activation (keys 9 and 7): the active-
                                effects countdown above the escalated
                                prices in the powerup strip
"""

import os
import random
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pygame

from constants import SCREEN_HEIGHT, SCREEN_WIDTH
from hud import draw_hud
from main import draw_credits
from tests._balance_sim import (
    SIM_BUY_CADENCE_S,
    SIM_DT,
    SIM_FPS,
    SIM_SEED,
    SimStats,
    click_target_pos,
    sim_world,
    step,
)
import sound

OUT = "/tmp/obv-evidence"
os.makedirs(OUT, exist_ok=True)

pygame.init()
sound.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
random.seed(SIM_SEED)

scratch = tempfile.mkdtemp(prefix="proof-integration-")
old_cwd = os.getcwd()
os.chdir(scratch)

try:
    with sim_world(os.path.join(scratch, "game_save.json")) as world:
        world["_prev_asteroids"] = set(world["asteroids"])
        economy = world["economy"]
        shop = world["shop"]

        # Seed enough to buy drones plus two powerup activations — a
        # fixture for the panel states, not a measurement.
        economy.credits = 1500.0
        assert shop.purchase("drone") is not None

        # ~6 sim-seconds of the real loop: rocks on screen, drones firing,
        # credits minting, floating +N numbers.
        stats = SimStats()
        click_due = 0.0
        buy_due = SIM_BUY_CADENCE_S
        for frame in range(6 * SIM_FPS):
            sim_time = frame * SIM_DT
            world["_click_pos"] = click_target_pos(world)
            click_due, buy_due = step(world, stats, sim_time, click_due, buy_due)
        assert len(world["asteroids"]) > 0, "field never populated"
        assert len(world["drones"].turrets) >= 1, "drones never synced"

        def render_and_save(filename):
            """main()'s render block, verbatim order, then save the PNG."""
            world_surf = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            world_surf.fill("black")
            for each in world["drawable"]:
                each.draw(world_surf)
            screen.fill("black")
            screen.blit(world_surf, world["shake"].offset())
            game = world["game"]
            draw_credits(screen, economy.credits)
            world["drones"].draw(screen, world["player"])
            shop.draw_panel(screen)
            shop.draw_powerups(screen)
            draw_hud(screen, game.score, lives=game.lives, wave=game.wave,
                     muted=game.muted)
            pygame.image.save(screen, f"{OUT}/{filename}")

        # Panel state 1: pre-activation — affordable cells bright.
        render_and_save("integration_shop_panel.png")

        # Panel state 2: Overdrive + Gold Rush running — the active-effects
        # countdown shows above escalated per-use prices.
        assert shop.handle_powerup_key(pygame.K_9) == "overdrive"
        assert shop.handle_powerup_key(pygame.K_7) == "gold_rush"
        world["_click_pos"] = click_target_pos(world)
        step(world, stats, 6.0, click_due, buy_due)
        actives = economy.active_powerups()
        assert len(actives) == 2, f"expected two running effects, got {actives}"

        render_and_save("integration_powerup_active.png")
finally:
    os.chdir(old_cwd)

print(f"Integration evidence written to {OUT}:")
for name in ("integration_shop_panel.png", "integration_powerup_active.png"):
    print(f"  {OUT}/{name}")
