"""Headless balance-simulation harness for the idle integration pass.

Replicates main()'s per-frame work in main()'s exact order, driven by
direct method calls instead of injected events: no rendering, no wall
clock — dt is a fixed 1/60, so a simulated minute costs 3,600 cheap
frames. The player shoots every frame (space held — Player.shoot()
enforces the cooldown itself), a simulated clicker spams
SIM_CLICKS_PER_SECOND clicks at the nearest rock through the same
asteroid_at → take_chip path the MOUSEBUTTONDOWN branch runs, and an
idle-style buyer purchases the cheapest affordable upgrade every
SIM_BUY_CADENCE seconds.

Two deliberate simplifications, both conservative for the measurements
this harness feeds:

- The simulated player never dies — lives are topped up each frame.
  The out-scaling question is income vs field density, not survival;
  deaths would only suppress the income side of the comparison.
- The buyer never activates powerups in the out-scaling run. Gold Rush
  would only accelerate the income side, so excluding it biases the
  check against the economy, not for it.

The nuke and the shop-purchase pipeline are exercised end-to-end by
run_nuke_scenario instead. Autosave is not simulated — persistence is
covered by the unit tests, and a mid-sim save would only rewrite the
same idle_* keys it read.

Standalone entry (from the repo root) prints the ten-minute playtest
report used for the balance pass:

    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
        uv run python -m tests._balance_sim
"""

import os
import random
import sys
import tempfile
from contextlib import contextmanager

import pygame

from asteroid import Asteroid
from asteroidfield import AsteroidField
from constants import (
    PLAYER_START_LIVES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from drones import DroneBay, nearest_asteroid
from economy import Economy
from game import Game
from hud import WaveBanner, points_for
from main import (
    FloatingText,
    asteroid_at,
    click_damage,
    destroyed_asteroids,
    handle_collisions,
    maybe_advance_wave,
    nuke_field,
)
from particles import Particle, Shake
from player import Player
from powerups import PowerUp
from shop import Shop
from shot import Shot
import sound

SIM_FPS = 60
SIM_DT = 1.0 / SIM_FPS

# Clicker and buyer cadence defaults: a human-grade clicker spams ~6
# clicks/s; the buyer checks once per half-second, buying the cheapest
# affordable upgrade (genre-typical: keep every curve moving).
SIM_CLICKS_PER_SECOND = 6.0
SIM_BUY_CADENCE_S = 0.5

# Fixed seed: the field's spawns, speeds, and drop rolls are random, so
# the sim is deterministic end to end — same numbers every run.
SIM_SEED = 20260924

# Classes whose `containers` build_world re-points; the sim_world context
# manager restores them so a sim cannot leak group wiring into other tests.
_CONTAINER_CLASSES = (
    Asteroid,
    Shot,
    PowerUp,
    Particle,
    AsteroidField,
    FloatingText,
    Player,
)


class SimStats:
    """What the balance pass reads out of one simulated session."""

    def __init__(self):
        self.duration_s = 0.0
        self.afford_nanoblade_s = None  # first time the 10-credit curve was payable
        self.minutes = []  # one dict per simulated minute
        self.total_minted = 0.0
        self.purchases = []  # (sim_time, name, level, cost)

    def minute(self, index):
        while len(self.minutes) <= index:
            self.minutes.append(
                {"minted": 0.0, "density_sum": 0.0, "density_samples": 0, "wave": 1}
            )
        return self.minutes[index]


def build_world(save_path):
    """The groups, containers, and owners main() builds, minus rendering."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    floaters = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)
    AsteroidField.containers = updatable
    FloatingText.containers = (floaters, updatable, drawable)
    Player.containers = (updatable, drawable)

    player1 = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    shake = Shake()
    game = Game(
        player1,
        asteroids,
        shots,
        powerups,
        save_path=save_path,
        particles=particles,
        shake=shake,
    )
    field = AsteroidField(game)
    banner = WaveBanner()
    banner.show(game.wave)

    economy = Economy(save_path=save_path)
    shop = Shop(economy, player1)
    drones = DroneBay(economy)

    return {
        "updatable": updatable,
        "drawable": drawable,
        "asteroids": asteroids,
        "shots": shots,
        "powerups": powerups,
        "player": player1,
        "shake": shake,
        "game": game,
        "field": field,
        "banner": banner,
        "economy": economy,
        "shop": shop,
        "drones": drones,
        "_click_pos": (SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2),
        "_prev_asteroids": set(),
    }


@contextmanager
def sim_world(save_path):
    """A built world whose container wiring is restored on exit."""
    before = [getattr(cls, "containers", None) for cls in _CONTAINER_CLASSES]
    try:
        yield build_world(save_path)
    finally:
        for cls, containers in zip(_CONTAINER_CLASSES, before):
            if containers is None:
                del cls.containers  # was never assigned — back to that state
            else:
                cls.containers = containers


def cheapest_affordable(shop):
    """The cheapest upgrade the ledger can pay right now, or None."""
    costs = sorted(
        (shop.economy.upgrade_cost(name), name) for name in shop.economy.levels
    )
    for cost, name in costs:
        if shop.economy.credits >= cost:
            return name
    return None


def click_target_pos(world):
    """Where the clicker clicks: the nearest rock's center, or screen middle."""
    target = nearest_asteroid(world["asteroids"], world["player"].position)
    if target is not None:
        world["_click_pos"] = (target.position.x, target.position.y)
    return world["_click_pos"]


def step(world, stats, sim_time, click_due, buy_due, clicks_per_second=SIM_CLICKS_PER_SECOND):
    """One simulated frame, in main()'s order.

    Returns the (click_due, buy_due) timers advanced by SIM_DT; the
    frame's minted credits are folded into stats.
    """
    economy = world["economy"]
    shop = world["shop"]
    asteroids = world["asteroids"]
    player1 = world["player"]

    # Event-pump equivalent: the clicker's MOUSEBUTTONDOWN. The probe sits
    # on the nearest rock, so asteroid_at returns exactly that rock — the
    # same function main() runs on a real click position.
    click_due -= SIM_DT
    if click_due <= 0 and clicks_per_second > 0:
        click_due = 1.0 / clicks_per_second
        target = asteroid_at(asteroids, world["_click_pos"])
        if target is not None:
            target.take_chip(click_damage(shop, economy))

    # Shop keys 1–4: the buyer's cheapest-affordable policy, one purchase
    # per check. Purchases route through shop.purchase — the real seam —
    # so effect application happens exactly as on a real keypress.
    buy_due -= SIM_DT
    if buy_due <= 0:
        buy_due = SIM_BUY_CADENCE_S
        name = cheapest_affordable(shop)
        if name is not None:
            purchase = shop.purchase(name)
            if purchase is not None:
                stats.purchases.append(
                    (sim_time, purchase.name, purchase.level, purchase.cost)
                )

    world["updatable"].update(SIM_DT)
    # Space held: shoot() enforces the (possibly upgraded) cooldown itself.
    player1.shoot()

    world["drones"].update(SIM_DT, player1, asteroids, world["shots"])
    handle_collisions(
        asteroids,
        world["shots"],
        player1,
        world["game"],
        world["powerups"],
        world["shake"],
    )
    maybe_advance_wave(
        world["game"],
        world["field"],
        world["banner"],
        world["player"],
        world["economy"],
    )
    world["banner"].update(SIM_DT)
    world["shake"].update(SIM_DT)

    economy.tick_powerups(SIM_DT)
    Asteroid.speed_scale = economy.chrono_scale()

    # Destruction → credits, exactly main()'s diff-and-mint block.
    for wreck in destroyed_asteroids(world["_prev_asteroids"], asteroids):
        payout = economy.mint(wreck.radius)
        stats.total_minted += payout
        stats.minute(int(sim_time // 60))["minted"] += payout
        FloatingText(wreck.position.x, wreck.position.y, payout)
    world["_prev_asteroids"] = set(asteroids)

    # The competent-player model: this player dodges well enough never to
    # lose a life, so game_over never fires (see module docstring).
    world["game"].lives = PLAYER_START_LIVES

    # First time the first Nanoblade level is payable (playtest A).
    if (
        stats.afford_nanoblade_s is None
        and economy.levels["nanoblade"] == 0
        and economy.credits >= economy.upgrade_cost("nanoblade")
    ):
        stats.afford_nanoblade_s = sim_time

    return click_due, buy_due


def run_session(seconds, save_path=None, clicks_per_second=SIM_CLICKS_PER_SECOND):
    """Simulate `seconds` of play on a fresh save; return SimStats.

    Runs with cwd pointed at a scratch directory (like main() would on a
    player's machine) so game_save.json and the JSONL logs never touch
    the repo. The sim keeps the HUD floaters and the field's pickups —
    the whole loop runs, not just the ledger.
    """
    scratch = scratch_for(save_path, "balance-sim-")
    save_path = os.path.join(scratch, "game_save.json")

    old_cwd = os.getcwd()
    os.chdir(scratch)
    try:
        pygame.init()
        sound.init()
        random.seed(SIM_SEED)

        stats = SimStats()
        stats.duration_s = seconds
        click_due = 0.0
        buy_due = SIM_BUY_CADENCE_S

        with sim_world(save_path) as world:
            world["_prev_asteroids"] = set(world["asteroids"])
            frames = int(seconds * SIM_FPS)
            for frame in range(frames):
                sim_time = frame * SIM_DT
                world["_click_pos"] = click_target_pos(world)
                click_due, buy_due = step(
                    world, stats, sim_time, click_due, buy_due, clicks_per_second
                )

                # Per-second density sample for the field-growth measurement.
                if frame % SIM_FPS == 0:
                    minute = stats.minute(int(sim_time // 60))
                    minute["density_sum"] += len(world["asteroids"])
                    minute["density_samples"] += 1
                    minute["wave"] = world["game"].wave
    finally:
        os.chdir(old_cwd)
    return stats


def scratch_for(save_path, prefix):
    """The scratch dir a scenario runs in: given, or a fresh temp dir."""
    if save_path is None:
        return tempfile.mkdtemp(prefix=prefix)
    return os.path.dirname(save_path)


def run_nuke_scenario(save_path=None):
    """Bounded end-to-end: shop purchases, drone income, one nuke.

    Returns a dict the balance tests check: the drone minted through the
    shared pipeline, and the nuke paid every rock on screen exactly once.
    """
    scratch = scratch_for(save_path, "nuke-sim-")
    save_path = os.path.join(scratch, "game_save.json")
    os.makedirs(scratch, exist_ok=True)

    old_cwd = os.getcwd()
    os.chdir(scratch)
    try:
        pygame.init()
        sound.init()
        random.seed(SIM_SEED)

        stats = SimStats()
        click_due = 0.0
        buy_due = SIM_BUY_CADENCE_S

        with sim_world(save_path) as world:
            world["_prev_asteroids"] = set(world["asteroids"])

            # Seed the ledger so a drone level is purchasable immediately —
            # a fixture, not a cheat: this gate is about the pipeline.
            world["economy"].credits = 2000.0
            purchase = world["shop"].purchase("drone")
            assert purchase is not None and purchase.name == "drone"

            drone_income_start = world["economy"].credits
            # ~4 sim-seconds: turret fires within 1.5s, shots travel ≤ ~1.3s.
            for frame in range(4 * SIM_FPS):
                sim_time = frame * SIM_DT
                world["_click_pos"] = click_target_pos(world)
                click_due, buy_due = step(
                    world, stats, sim_time, click_due, buy_due
                )
            drone_minted = world["economy"].credits - drone_income_start
            # The bay syncs from the Drones level on the first update; the
            # buyer may have grown the fleet further — at least one turret.
            assert len(world["drones"].turrets) >= 1
            assert drone_minted > 0, "shared pipeline paid nothing in 4s"

            # The nuke through the real key path (K_8), with the ledger
            # able to pay the escalating price (uses = 0 → base cost).
            economy = world["economy"]
            nuke_price = economy.powerup_price("nuke")
            assert economy.credits >= nuke_price, "scenario fixture underfunded"
            prev = set(world["asteroids"])
            expected = sum(points_for(rock.radius) for rock in prev)
            rock_tiers = sorted(rock.radius for rock in prev)

            pre_activation = economy.credits
            activated = world["shop"].handle_powerup_key(pygame.K_8)
            assert activated == "nuke"
            price_paid = pre_activation - economy.credits
            # main() splits the field right after the activation lands.
            nuke_field(world["asteroids"])
            field_empty = len(world["asteroids"]) == 0

            # The loop's diff pays the nuked parents — measure exactly that
            # block, not the whole frame. The payout scales by the live
            # income multiplier (Income levels bought in the window), same
            # as every mint.
            nuked = destroyed_asteroids(prev, world["asteroids"])
            expected *= economy.income_multiplier()
            nuke_payout = sum(economy.mint(wreck.radius) for wreck in nuked)

            # And the loop keeps running on the emptied field: one more frame.
            world["_prev_asteroids"] = set(world["asteroids"])
            world["_click_pos"] = click_target_pos(world)
            step(world, stats, 4.0, click_due, buy_due)
    finally:
        os.chdir(old_cwd)

    return {
        "pipeline_income_4s": drone_minted,
        "field_empty": field_empty,
        "nuke_payout": nuke_payout,
        "expected_payout": expected,
        "rock_tiers": rock_tiers,
        "paid_exactly_once": abs(nuke_payout - expected) < 1e-6,
        "nuke_price_paid": price_paid,
    }


def minute_mean_density(minute):
    return minute["density_sum"] / max(1, minute["density_samples"])


def print_report(stats):
    """The ten-minute playtest report for the PR body."""
    print(
        f"simulated {stats.duration_s / 60:.0f} minutes "
        f"(seed {SIM_SEED}, {SIM_CLICKS_PER_SECOND:.0f} clicks/s, "
        f"buy every {SIM_BUY_CADENCE_S:.1f}s)"
    )
    print(f"time to afford first Nanoblade: {stats.afford_nanoblade_s}s")
    print("min | credits/min | mean field density | wave")
    for index, minute in enumerate(stats.minutes, start=1):
        density = minute_mean_density(minute)
        print(
            f"{index:3d} | {minute['minted']:11.0f} | {density:18.1f} | "
            f"{minute['wave']}"
        )
    if len(stats.minutes) >= 10:
        first_half = sum(m["minted"] for m in stats.minutes[:5]) / 5
        second_half = sum(m["minted"] for m in stats.minutes[5:10]) / 5
        income_growth = second_half / first_half if first_half else float("inf")
        density_first = sum(minute_mean_density(m) for m in stats.minutes[:5]) / 5
        density_second = sum(minute_mean_density(m) for m in stats.minutes[5:10]) / 5
        density_growth = density_second / density_first if density_first else float("inf")
        print(f"income growth (min 6-10 vs 1-5): {income_growth:.2f}x")
        print(f"field density growth (min 6-10 vs 1-5): {density_growth:.2f}x")
        print(f"out-scaling holds: {income_growth > density_growth}")
    print(
        "purchases: "
        + ", ".join(
            f"{name} Lv{level} @{int(cost)}cr ({time:.0f}s)"
            for time, name, level, cost in stats.purchases
        )
    )


if __name__ == "__main__":
    horizon_s = float(sys.argv[1]) * 60 if len(sys.argv) > 1 else 600.0
    scratch = tempfile.mkdtemp(prefix="balance-sim-")
    report_stats = run_session(
        horizon_s, save_path=os.path.join(scratch, "game_save.json")
    )
    print_report(report_stats)
    print(
        "nuke scenario:",
        run_nuke_scenario(save_path=os.path.join(scratch, "nuke", "game_save.json")),
    )
