"""Headless balance-simulation harness for the idle integration pass.

Replicates main()'s per-frame work in main()'s exact order, driven by
direct method calls instead of injected events: no rendering, no wall
clock — dt is a fixed 1/60, so a simulated minute costs 3,600 cheap
frames. The insanity build rides the same order end to end: the hit-stop
gate produces the frame's sim dt (0.0 while a freeze holds, and the
clicker and buyer — event-pump work in main — run on the real frame dt
exactly as queued input does), saucers step explicitly with the player
and the enemy group, the threat clocks arm saucers and black holes, the
boss scheduler fields every fifth wave, the combo window drains on sim
time, and the live-hole registry is published before the world update.

The player shoots every frame (space held — Player.shoot() enforces the
cooldown itself), a simulated clicker spams SIM_CLICKS_PER_SECOND clicks
at the nearest rock through the same asteroid_at → take_chip path the
MOUSEBUTTONDOWN branch runs, an idle-style buyer purchases the cheapest
affordable upgrade every SIM_BUY_CADENCE seconds, a dodge-dash policy
spends the SHIFT panic whenever the nearest rock closes inside
SIM_DASH_DODGE_DISTANCE (through main.try_dash, the real wiring that
prices the dash in combo breaks), and a collector policy flies the ship
at the nearest drop inside SIM_COLLECT_RANGE — the move keys, so the
chaos pickups actually get opened.

Two deliberate simplifications, both conservative for the measurements
this harness feeds:

- The simulated player never dies — lives are topped up each frame.
  The out-scaling question is income vs field density, not survival;
  deaths would only suppress the income side of the comparison (and
  the pressure read is the threats' tempo, not the ship's end).
- The buyer never activates powerups in the out-scaling run. Gold Rush
  would only accelerate the income side, so excluding it biases the
  check against the economy, not for it.

The nuke and the shop-purchase pipeline are exercised end-to-end by
run_nuke_scenario instead. Autosave is not simulated — persistence is
covered by the unit tests, and a mid-sim save would only rewrite the
same idle_* keys it read. Event counting rides an event tap (the game
modules' log_event bindings swapped for a counter): the JSONL logger
stops after 16 real seconds, so a long sim keeps its trail in
SimStats.events instead of a log file.

Standalone entry (from the repo root) prints the ten-minute playtest
report used for the balance pass, the insanity pressure included:

    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
        uv run python -m tests._balance_sim

`--seed N` runs a different fixed session (the default pins the
playtest numbers); `--json` prints the full report as JSON and exits
nonzero when a sanity check fails — accounting identities on any
horizon, signs of life from every feature past SANITY_HORIZON_S.
"""

import argparse
import json
import os
import random
import sys
import tempfile
from contextlib import contextmanager

# Before pygame is imported: its support banner prints to stdout and would
# corrupt --json output.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

import asteroid as asteroid_module
import blackhole as blackhole_module
import game as game_module
import hud as hud_module
import main as main_module
import player as player_module
import saucer as saucer_module
from asteroid import Asteroid, Boss
from asteroidfield import AsteroidField
from blackhole import (
    BlackHole,
    BlackHoleScheduler,
    spawn_position as hole_position,
)
from constants import (
    BOSS_WAVE_INTERVAL,
    COMBO_CAP,
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
    HitStop,
    asteroid_at,
    bomb_clear,
    click_damage,
    destroyed_asteroids,
    effective_frame_dt,
    freeze_for_destructions,
    handle_collisions,
    maybe_advance_wave,
    maybe_boss_wave,
    nuke_field,
    try_dash,
)
from particles import Particle, Shake
from player import Player
from powerups import PowerUp
from saucer import Saucer, SaucerScheduler, SaucerShot, spawn_side_position
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

# The dodge-dash policy: when the nearest rock closes inside this range the
# sim spends its SHIFT panic — cooldown, i-frames, and the combo break it
# prices. Human-grade reflexes, a few dashes a minute under pressure.
SIM_DASH_DODGE_DISTANCE = 130.0

# The collector policy: a competent player also flies at the nearest drop
# (inside this range, at this cruise speed) — mystery opens and curse
# reveals are the chaos features' pressure read, and they only exist if
# drops get picked up. Direct position stepping, the move-key equivalent.
SIM_COLLECT_RANGE = 240.0
SIM_COLLECT_SPEED = 260.0

# Horizons this long must show every feature alive (the sanity gates);
# shorter runs report what they saw without failing the signs-of-life
# checks — test_balance.py's 35s probe is one of those.
SANITY_HORIZON_S = 120.0

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
    SaucerShot,
    Saucer,
    BlackHole,
)

# Marks "this class had no containers of its own" in the sim_world snapshot.
_MISSING = object()


class EventTap:
    """Counts log_event calls by type while a session runs.

    A counting stand-in, not a pass-through: the JSONL logger stops after
    16 real seconds per run — a ten-minute sim would log only its first
    second — so the sim swaps the bindings wholesale and the scratch dir
    stays clean. The counts are the sim's pressure instrument."""

    def __init__(self):
        self.counts = {}

    def __call__(self, event_type, **details):
        self.counts[event_type] = self.counts.get(event_type, 0) + 1


# Every game module binds log_event at import time (`from logger import
# log_event`); the tap swaps each module's own binding and restores it,
# leaving the logger module itself untouched.
_LOG_EVENT_MODULES = (
    main_module,
    asteroid_module,
    player_module,
    blackhole_module,
    game_module,
    hud_module,
    saucer_module,
)


@contextmanager
def event_tap():
    """Swap every game module's log_event for a counting tap; restore on exit."""
    tap = EventTap()
    originals = {module: module.log_event for module in _LOG_EVENT_MODULES}
    for module in _LOG_EVENT_MODULES:
        module.log_event = tap
    try:
        yield tap
    finally:
        for module, original in originals.items():
            module.log_event = original


class SimStats:
    """What the balance pass reads out of one simulated session."""

    def __init__(self):
        self.duration_s = 0.0
        self.afford_nanoblade_s = None  # first time the 10-credit curve was payable
        self.minutes = []  # one dict per simulated minute
        self.total_minted = 0.0
        self.purchases = []  # (sim_time, name, level, cost)
        # Insanity pressure (insanity build): the state side of the read —
        # the event tap supplies the counting side in `events`.
        self.events = {}
        self.top_chain = 0
        self.best_multiplier = 1.0
        self.frozen_frames = 0
        self.dashes = 0
        self.bombs = 0
        self.end = {}  # final group sizes, wave, and score, read in-session

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
    # Insanity threats: enemy fire and world hazards get their own groups —
    # `shots` stays the player-and-drone group, exactly main()'s wiring.
    enemy_shots = pygame.sprite.Group()
    saucers = pygame.sprite.Group()
    blackholes = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    PowerUp.containers = (powerups, updatable, drawable)
    Particle.containers = (particles, updatable, drawable)
    AsteroidField.containers = updatable
    FloatingText.containers = (floaters, updatable, drawable)
    SaucerShot.containers = (enemy_shots, updatable, drawable)
    Saucer.containers = (saucers, drawable)
    BlackHole.containers = (blackholes, updatable, drawable)
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

    # Insanity core/threats: the freeze gate and the threat clocks live in
    # main (they gate and schedule; they are not run state) — the sim steps
    # them in the same order.
    hit_stop = HitStop()
    saucer_clock = SaucerScheduler()
    hole_clock = BlackHoleScheduler()

    world = {
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
        "enemy_shots": enemy_shots,
        "saucers": saucers,
        "blackholes": blackholes,
        "hit_stop": hit_stop,
        "saucer_clock": saucer_clock,
        "hole_clock": hole_clock,
        "_click_pos": (SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2),
        "_prev_asteroids": set(),
    }
    # Bomb pickup (insanity chaos): the field-clear callback main injects —
    # the ship never owns the world, and the bought nuke's exact path is
    # what a collected bomb must fire.
    world["player"].bomb_field = lambda: bomb_clear(
        world["hit_stop"], world["shake"], world["asteroids"]
    )
    return world


@contextmanager
def sim_world(save_path):
    """A built world whose container wiring is restored on exit.

    The snapshot reads each class's OWN __dict__, not getattr: SaucerShot
    inherits Shot.containers until main() re-points it, so an inherited
    value saved as if it were real would come back pinned as a class
    attribute — a leak past the sim."""
    before = [
        (cls, cls.__dict__.get("containers", _MISSING))
        for cls in _CONTAINER_CLASSES
    ]
    try:
        yield build_world(save_path)
    finally:
        for cls, containers in before:
            if containers is _MISSING:
                continue  # never had its own containers — nothing to restore
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


def nearest_powerup(group, position):
    """The nearest pickup to `position`, or None — the collector's target."""
    best = None
    best_dist = float("inf")
    for sprite in group:
        dist = sprite.position.distance_to(position)
        if dist < best_dist:
            best = sprite
            best_dist = dist
    return best


def click_target_pos(world):
    """Where the clicker clicks: the nearest rock's center, or screen middle."""
    target = nearest_asteroid(world["asteroids"], world["player"].position)
    if target is not None:
        world["_click_pos"] = (target.position.x, target.position.y)
    return world["_click_pos"]


def step(world, stats, sim_time, click_due, buy_due,
         clicks_per_second=SIM_CLICKS_PER_SECOND):
    """One simulated frame, in main()'s order — the insanity loop included.

    The event-pump work (clicker, buyer, dodge-dash) runs on the real
    frame dt exactly as queued input does in main — it lands even while a
    freeze holds; the world then steps on the gated sim dt (0.0 while a
    hit-stop freeze runs). Saucers update explicitly with the player and
    the enemy group, the threat clocks arm saucers and black holes, the
    boss scheduler fields every fifth wave, and the combo window drains
    on sim time.

    Returns the (click_due, buy_due) timers advanced by SIM_DT; the
    frame's minted credits are folded into stats.
    """
    economy = world["economy"]
    shop = world["shop"]
    asteroids = world["asteroids"]
    player1 = world["player"]
    game = world["game"]
    hit_stop = world["hit_stop"]

    # Event-pump equivalent: the clicker's MOUSEBUTTONDOWN. The probe sits
    # on the nearest rock, so asteroid_at returns exactly that rock — the
    # same function main() runs on a real click position. A click kill is
    # still a destruction: one base beat, combo-free.
    click_due -= SIM_DT
    if click_due <= 0 and clicks_per_second > 0:
        click_due = 1.0 / clicks_per_second
        target = asteroid_at(asteroids, world["_click_pos"])
        if target is not None:
            destroyed = target.take_chip(click_damage(shop, economy))
            freeze_for_destructions(hit_stop, 1 if destroyed else 0)

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

    # The dodge-dash policy (insanity core): when the nearest rock closes
    # in, spend the SHIFT panic — cooldown, i-frames, and the combo break
    # it prices. try_dash is main's real wiring, combo break included.
    target = nearest_asteroid(asteroids, player1.position)
    if (
        game.state == "playing"
        and target is not None
        and target.position.distance_to(player1.position) < SIM_DASH_DODGE_DISTANCE
        and try_dash(player1, game)
    ):
        stats.dashes += 1

    # The freeze-frame gate (insanity core): the freeze ticks on the real
    # frame dt; the world gets 0.0 while it holds, so a long request can
    # never stall the loop.
    hit_stop.update(SIM_DT)
    sim_dt = effective_frame_dt(SIM_DT, hit_stop)
    if hit_stop.frozen:
        stats.frozen_frames += 1
    blackhole_module.refresh_live_holes(world["blackholes"])

    # The collector policy (move keys): fly at the nearest drop within
    # reach, stepping position directly like main()'s movement keys — and
    # a frozen frame moves nobody (sim_dt is 0.0). Mystery opens and curse
    # reveals only exist if drops get picked up.
    drop = nearest_powerup(world["powerups"], player1.position)
    if (
        game.state == "playing"
        and drop is not None
        and drop.position.distance_to(player1.position) <= SIM_COLLECT_RANGE
    ):
        offset = drop.position - player1.position
        step_len = min(SIM_COLLECT_SPEED * sim_dt, offset.length())
        if step_len > 0:
            player1.position += offset.normalize() * step_len

    world["updatable"].update(sim_dt)
    # Space held: shoot() enforces the (possibly upgraded) cooldown itself;
    # a frozen frame never pulls the trigger (player.update's dt>0 guard).
    if sim_dt > 0:
        player1.shoot()

    world["drones"].update(sim_dt, player1, asteroids, world["shots"])

    # Saucers update explicitly, not through the group pass (insanity
    # threats): their step needs the player and the enemy group, which the
    # updatable pass doesn't forward.
    world["saucers"].update(sim_dt, player1, world["enemy_shots"])

    # Threat spawn clocks (insanity threats): saucers from wave 2, black
    # holes from wave 3 — never during game over, and a hole never opens
    # during a boss wave (the scheduler is told directly).
    if game.state == "playing":
        kind = world["saucer_clock"].update(sim_dt, game.wave)
        if kind is not None:
            Saucer(*spawn_side_position(kind), kind)
        if world["hole_clock"].update(
            sim_dt, game.wave, game.wave % BOSS_WAVE_INTERVAL == 0
        ):
            BlackHole(*hole_position())

    handle_collisions(
        asteroids,
        world["shots"],
        player1,
        game,
        world["powerups"],
        world["shake"],
        hit_stop=hit_stop,
        saucers=world["saucers"],
        enemy_shots=world["enemy_shots"],
    )
    maybe_advance_wave(
        game,
        world["field"],
        world["banner"],
        player1,
        economy,
    )
    maybe_boss_wave(game, world["field"])
    game.tick(sim_dt)  # insanity core: the combo window drains on sim time
    world["banner"].update(sim_dt)
    world["shake"].update(SIM_DT)

    # Bought powerups tick on the dt-timer pattern: expire effects, then
    # publish the chrono scale the whole field reads this frame.
    economy.tick_powerups(sim_dt)
    Asteroid.speed_scale = economy.chrono_scale()
    # Insanity chaos: while HOMING runs, every friendly shot steers (the
    # speed_scale precedent — one class-level write per frame).
    Shot.homing_targets = asteroids if player1.has_homing else None

    # Destruction → credits, exactly main()'s diff-and-mint block. Boss
    # wrecks route around the mint — score-only, logged where main logs
    # it (through main's binding, so the tap sees the defeat).
    for wreck in destroyed_asteroids(world["_prev_asteroids"], asteroids):
        if isinstance(wreck, Boss):
            main_module.log_event("boss_defeated", wave=game.wave)
            continue
        payout = economy.mint(wreck.radius)
        main_module.log_event("credit_minted", amount=payout)
        stats.total_minted += payout
        stats.minute(int(sim_time // 60))["minted"] += payout
        FloatingText(wreck.position.x, wreck.position.y, payout)
    world["_prev_asteroids"] = set(asteroids)

    # The competent-player model: this player dodges well enough never to
    # lose a life, so game_over never fires (see module docstring).
    world["game"].lives = PLAYER_START_LIVES

    # The pressure read, per frame: the chain's reach and the multiplier
    # the HUD would show at its best moment.
    stats.top_chain = max(stats.top_chain, game.combo.top)
    stats.best_multiplier = max(stats.best_multiplier, game.combo.best_multiplier)

    # First time the first Nanoblade level is payable (playtest A).
    if (
        stats.afford_nanoblade_s is None
        and economy.levels["nanoblade"] == 0
        and economy.credits >= economy.upgrade_cost("nanoblade")
    ):
        stats.afford_nanoblade_s = sim_time

    return click_due, buy_due


def run_session(seconds, save_path=None, clicks_per_second=SIM_CLICKS_PER_SECOND,
                seed=SIM_SEED):
    """Simulate `seconds` of play on a fresh save; return SimStats.

    Runs with cwd pointed at a scratch directory (like main() would on a
    player's machine) so game_save.json and the JSONL logs never touch
    the repo, and with every game module's log_event swapped for a
    counting tap — the JSONL logger stops after 16 real seconds, so a long
    sim keeps its event trail in stats.events instead of a log file. The
    sim keeps the HUD floaters and the field's pickups — the whole loop
    runs, not just the ledger.
    """
    scratch = scratch_for(save_path, "balance-sim-")
    save_path = os.path.join(scratch, "game_save.json")

    old_cwd = os.getcwd()
    os.chdir(scratch)
    try:
        pygame.init()
        sound.init()
        random.seed(seed)

        stats = SimStats()
        stats.duration_s = seconds
        click_due = 0.0
        buy_due = SIM_BUY_CADENCE_S

        with event_tap() as tap, sim_world(save_path) as world:
            world["_prev_asteroids"] = set(world["asteroids"])
            # Bomb counting rides the injected callback: the sim wraps
            # main's wiring — the real field clear still runs.
            base_bomb_field = world["player"].bomb_field

            def bomb_field():
                stats.bombs += 1
                base_bomb_field()

            world["player"].bomb_field = bomb_field

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

            stats.end = {
                "final_wave": world["game"].wave,
                "score": world["game"].score,
                "saucers": len(world["saucers"]),
                "bosses": sum(
                    1 for rock in world["asteroids"] if isinstance(rock, Boss)
                ),
                "holes": len(world["blackholes"]),
            }
        stats.events = dict(tap.counts)
    finally:
        os.chdir(old_cwd)
    return stats


def scratch_for(save_path, prefix):
    """The scratch dir a scenario runs in: given, or a fresh temp dir."""
    if save_path is None:
        return tempfile.mkdtemp(prefix=prefix)
    return os.path.dirname(save_path)


def run_nuke_scenario(save_path=None, seed=SIM_SEED):
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
        random.seed(seed)

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


def build_report(stats, seed, nuke_scenario=None):
    """Everything one session measured, JSON-ready.

    The balance read is unchanged — income vs field density per minute —
    and the insanity blocks add the pressure the release needs to see:
    the combo chain's reach, the bosses' and saucers' toll, the holes'
    comings and goings, and the chaos drops' gamble."""
    events = stats.events
    saucer_spawned = events.get("saucer_spawned", 0)
    saucer_defeated = events.get("saucer_defeated", 0)
    hole_spawned = events.get("blackhole_spawned", 0)
    hole_despawned = events.get("blackhole_despawned", 0)
    report = {
        "seed": seed,
        "duration_s": stats.duration_s,
        "final_wave": stats.end.get("final_wave"),
        "score": stats.end.get("score"),
        "afford_nanoblade_s": stats.afford_nanoblade_s,
        "total_minted": stats.total_minted,
        "player_hits": events.get("player_hit", 0),
        "combo": {
            "top_chain": stats.top_chain,
            "best_multiplier": stats.best_multiplier,
            "cap": COMBO_CAP,
            "milestones": events.get("combo_milestone", 0),
            "breaks": events.get("combo_break", 0),
        },
        "hit_stop": {
            "frozen_frames": stats.frozen_frames,
            "frozen_fraction": (
                stats.frozen_frames / (stats.duration_s * SIM_FPS)
                if stats.duration_s
                else 0.0
            ),
        },
        "dash_uses": stats.dashes,
        "bosses": {
            "spawned": events.get("boss_spawned", 0),
            "defeated": events.get("boss_defeated", 0),
            "alive_at_end": stats.end.get("bosses", 0),
            "hits": events.get("boss_hit", 0),
        },
        "saucers": {
            "spawned": saucer_spawned,
            "defeated": saucer_defeated,
            "culled": saucer_spawned - saucer_defeated - stats.end.get("saucers", 0),
            "alive_at_end": stats.end.get("saucers", 0),
        },
        "blackholes": {
            "spawned": hole_spawned,
            "despawned": hole_despawned,
            "alive_at_end": stats.end.get("holes", 0),
        },
        "chaos": {
            "drops": events.get("powerup_spawned", 0),
            "collected": events.get("powerup_collected", 0),
            "mystery_opens": events.get("mystery_collected", 0),
            "curse_reveals": events.get("curse_revealed", 0),
            "bomb_clears": stats.bombs,
        },
        "nuke_scenario": nuke_scenario,
        "minutes": stats.minutes,
        "purchases": stats.purchases,
    }
    report["sanity"] = sanity_checks(report)
    return report


def sanity_checks(report):
    """Structural invariants, not balance judgments.

    Accounting identities must hold on any horizon — no lost saucer, no
    resurrected boss, no well that outlives its own clock — and a long-
    enough session must show every feature alive. The curves themselves
    stay ungated: they are the read, and constants.py is the dial."""
    failures = []

    bosses = report["bosses"]
    if bosses["spawned"] != bosses["defeated"] + bosses["alive_at_end"]:
        failures.append("bosses: spawned != defeated + alive_at_end")

    saucers = report["saucers"]
    if saucers["spawned"] < saucers["defeated"] + saucers["alive_at_end"]:
        failures.append("saucers: defeated + alive_at_end exceeds spawned")

    holes = report["blackholes"]
    if holes["spawned"] != holes["despawned"] + holes["alive_at_end"]:
        failures.append("blackholes: spawned != despawned + alive_at_end")

    if report["duration_s"] >= SANITY_HORIZON_S:
        if report["combo"]["top_chain"] < 2:
            failures.append("combo: no chain ever reached 2 kills")
        if report["combo"]["best_multiplier"] < 2.0:
            failures.append("combo: the multiplier never reached x2")
        for label, count in (
            ("bosses", bosses["spawned"]),
            ("boss defeats", bosses["defeated"]),
            ("saucers", saucers["spawned"]),
            ("blackholes", holes["spawned"]),
            ("blackhole despawns", holes["despawned"]),
            ("dashes", report["dash_uses"]),
            ("mystery opens", report["chaos"]["mystery_opens"]),
            ("curse reveals", report["chaos"]["curse_reveals"]),
            ("player hits", report["player_hits"]),
        ):
            if count < 1:
                failures.append(
                    f"{label}: never seen in {report['duration_s']:.0f}s"
                )
        if report["hit_stop"]["frozen_frames"] < 1:
            failures.append("hit_stop: the frame never froze")

    return {"ok": not failures, "failures": failures}


def minute_mean_density(minute):
    return minute["density_sum"] / max(1, minute["density_samples"])


def print_report(stats, seed=SIM_SEED):
    """The ten-minute playtest report for the PR body."""
    print(
        f"simulated {stats.duration_s / 60:.0f} minutes "
        f"(seed {seed}, {SIM_CLICKS_PER_SECOND:.0f} clicks/s, "
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
    events = stats.events
    print(
        "insanity: "
        f"top chain {stats.top_chain} (best x{stats.best_multiplier:.2f}), "
        f"bosses {events.get('boss_spawned', 0)} spawned / "
        f"{events.get('boss_defeated', 0)} defeated, "
        f"saucers {events.get('saucer_spawned', 0)} spawned / "
        f"{events.get('saucer_defeated', 0)} defeated, "
        f"holes {events.get('blackhole_spawned', 0)} spawned, "
        f"{stats.dashes} dashes, "
        f"{events.get('curse_revealed', 0)} curses over "
        f"{events.get('mystery_collected', 0)} mystery opens, "
        f"{stats.frozen_frames} frozen frames"
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


def parse_args(argv=None):
    """The standalone CLI: horizon in minutes, a fixed seed, JSON out."""
    parser = argparse.ArgumentParser(
        description="Headless balance sim of main()'s loop — the insanity "
        "build's combo/boss/saucer pressure included.",
    )
    parser.add_argument(
        "minutes",
        nargs="?",
        type=float,
        default=10.0,
        help="session horizon in minutes (default 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SIM_SEED,
        help=f"random seed for the whole session (default {SIM_SEED})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full report as JSON; exit 1 when a sanity check fails",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    horizon_s = args.minutes * 60
    scratch = tempfile.mkdtemp(prefix="balance-sim-")
    report_stats = run_session(
        horizon_s,
        save_path=os.path.join(scratch, "game_save.json"),
        seed=args.seed,
    )
    nuke_report = run_nuke_scenario(
        save_path=os.path.join(scratch, "nuke", "game_save.json"),
        seed=args.seed,
    )
    report = build_report(report_stats, args.seed, nuke_scenario=nuke_report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report_stats, seed=args.seed)
        print("nuke scenario:", nuke_report)
        print("sanity:", report["sanity"])
    sys.exit(0 if report["sanity"]["ok"] else 1)
