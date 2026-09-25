"""Tests for persisted achievements + the queued toast banner (Tier 2).

The first block drives the pure evaluator with synthetic EventStats and pins
every threshold boundary — each award fires exactly once, at its threshold,
in table order. The toast block pins the FIFO: one visible at a time, dt-timer
expiry, and the pure slide geometry. The persistence block is the designed
tripwire: unlocking merges the `achievements` key through the shared save
loader, so a fresh-dict write (which would erase idle_*/high_score) fails
these tests. The wiring block proves the snapshot builder reads the live
owners and that both restart hooks leave the lifetime set alone. The last
block renders the toast headless and asserts pixels.
"""

import json

import pygame

from achievements import (
    ACHIEVEMENTS,
    ACHIEVEMENTS_BY_ID,
    Achievements,
    EventStats,
    ToastQueue,
    evaluate_achievements,
    event_stats_from,
    load_unlocked,
    toast_y,
)
from constants import (
    ACHIEVEMENT_SCORE_THRESHOLD,
    ACHIEVEMENT_WAVE_THRESHOLD,
    PALETTE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TOAST_SEAT_Y,
    TOAST_SLIDE_SECONDS,
    TOAST_SECONDS,
)
from game import Game
from hud import Score, WaveBanner
from main import restart_run
from player import Player
from asteroid import Asteroid
from asteroidfield import AsteroidField
from economy import Economy
from shot import Shot


def _stats(**overrides):
    """A synthetic snapshot: all triggers off unless overridden."""
    base = dict(
        score=0.0,
        wave=1,
        nuke_uses=0,
        drone_level=0,
        high_score_beaten=False,
    )
    base.update(overrides)
    return EventStats(**base)


# --- the pure threshold evaluation -------------------------------------------


def test_fresh_stats_fire_nothing():
    assert evaluate_achievements(set(), _stats()) == []


def test_each_award_fires_exactly_at_its_threshold():
    empty = set()
    cases = [
        (_stats(nuke_uses=1), "first_nuke"),
        (_stats(wave=ACHIEVEMENT_WAVE_THRESHOLD), "wave_5"),
        (_stats(score=ACHIEVEMENT_SCORE_THRESHOLD), "score_10000"),
        (_stats(drone_level=1), "first_drone"),
        (_stats(high_score_beaten=True), "high_score_beaten"),
    ]
    for stats, award_id in cases:
        newly = evaluate_achievements(empty, stats)
        assert [defn.id for defn in newly] == [award_id]


def test_one_below_each_threshold_fires_nothing():
    empty = set()
    assert evaluate_achievements(set(), _stats(nuke_uses=0)) == []
    assert evaluate_achievements(
        empty, _stats(wave=ACHIEVEMENT_WAVE_THRESHOLD - 1)
    ) == []
    assert evaluate_achievements(
        empty, _stats(score=ACHIEVEMENT_SCORE_THRESHOLD - 1)
    ) == []
    assert evaluate_achievements(empty, _stats(drone_level=0)) == []
    assert evaluate_achievements(empty, _stats(high_score_beaten=False)) == []


def test_all_at_once_returns_table_order():
    stats = _stats(
        nuke_uses=1,
        wave=ACHIEVEMENT_WAVE_THRESHOLD,
        score=ACHIEVEMENT_SCORE_THRESHOLD,
        drone_level=1,
        high_score_beaten=True,
    )
    newly = evaluate_achievements(set(), stats)
    assert [defn.id for defn in newly] == [defn.id for defn in ACHIEVEMENTS]


def test_unlocked_awards_never_refire():
    stats = _stats(
        nuke_uses=1,
        wave=ACHIEVEMENT_WAVE_THRESHOLD,
        score=ACHIEVEMENT_SCORE_THRESHOLD,
        drone_level=1,
        high_score_beaten=True,
    )
    unlocked = {defn.id for defn in ACHIEVEMENTS}
    assert evaluate_achievements(unlocked, stats) == []


def test_every_award_has_a_unique_id_and_title():
    ids = [defn.id for defn in ACHIEVEMENTS]
    assert len(ids) == len(set(ids)) == 5
    assert ACHIEVEMENTS_BY_ID.keys() == set(ids)
    assert all(defn.title.strip() for defn in ACHIEVEMENTS)


# --- the toast queue: FIFO, one at a time, dt expiry -------------------------


def test_fresh_queue_is_invisible():
    queue = ToastQueue()
    assert not queue.visible
    queue.update(0.5)
    assert not queue.visible


def test_toasts_show_one_at_a_time_in_fifo_order():
    queue = ToastQueue(duration=3.0)
    queue.show("FIRST")
    queue.show("SECOND")
    queue.show("THIRD")
    assert not queue.visible  # nothing until the first update seats one
    queue.update(0.0)
    assert queue.visible and queue.current == "FIRST"
    assert queue.queue == ["SECOND", "THIRD"]
    queue.update(1.0)
    assert queue.current == "FIRST"  # seated toast is the only one visible
    queue.update(2.0)  # total 3.0s seated: expires, SECOND steps in
    assert queue.current == "SECOND"
    queue.update(3.0)
    assert queue.current == "THIRD"
    queue.update(3.0)
    assert not queue.visible and queue.queue == []


def test_queued_toast_waits_out_the_seated_one():
    queue = ToastQueue(duration=3.0)
    queue.show("FIRST")
    queue.show("SECOND")
    queue.update(0.0)
    queue.update(1.0)
    assert queue.current == "FIRST"  # FIFO, not a swap
    assert queue.queue == ["SECOND"]


def test_toast_expires_on_the_dt_timer_alone():
    queue = ToastQueue(duration=3.0)
    queue.show("FIRST")
    queue.update(0.0)
    # many small steps behave like one big one — no wall clock anywhere
    for _ in range(6):
        queue.update(0.5)
    assert not queue.visible
    queue.update(0.0)
    assert not queue.visible  # nothing queued: the seat stays empty


def test_toast_slide_geometry_hides_holds_and_mirrors_out():
    duration, height = TOAST_SECONDS, 40.0
    assert toast_y(0.0, duration, height) == -height
    assert toast_y(-0.5, duration, height) == -height
    mid_slide = toast_y(TOAST_SLIDE_SECONDS / 2, duration, height)
    assert -height < mid_slide < TOAST_SEAT_Y
    assert toast_y(TOAST_SLIDE_SECONDS, duration, height) == TOAST_SEAT_Y
    assert toast_y(duration / 2, duration, height) == TOAST_SEAT_Y
    assert toast_y(duration - TOAST_SLIDE_SECONDS, duration, height) == TOAST_SEAT_Y
    mid_out = toast_y(duration - TOAST_SLIDE_SECONDS / 2, duration, height)
    assert -height < mid_out < TOAST_SEAT_Y
    assert toast_y(duration, duration, height) == -height
    assert toast_y(duration + 1.0, duration, height) == -height


# --- the save-merge tripwire --------------------------------------------------

PRE_EXISTING_SAVE = {
    "high_score": 4242,
    "muted": True,
    "volume": 60,
    "idle_credits": 1234.5,
    "idle_levels": {"drone": 2, "income": 1},
    "idle_powerup_uses": {"nuke": 3},
    "idle_last_seen": 987654.0,
}


def test_unlock_merges_and_preserves_other_features_keys(tmp_path):
    path = tmp_path / "game_save.json"
    path.write_text(json.dumps(PRE_EXISTING_SAVE))
    achievements = Achievements(save_path=path)
    assert achievements.unlocked == set()

    newly = achievements.evaluate(_stats(high_score_beaten=True))
    assert [defn.id for defn in newly] == ["high_score_beaten"]

    merged = json.loads(path.read_text())
    assert merged["achievements"] == ["high_score_beaten"]
    for key, value in PRE_EXISTING_SAVE.items():
        assert merged[key] == value, f"the merge clobbered {key}"


def test_unlocked_persist_across_instances_and_never_refire(tmp_path):
    path = tmp_path / "game_save.json"
    achievements = Achievements(save_path=path)
    achievements.evaluate(_stats(nuke_uses=1))

    again = Achievements(save_path=path)
    assert again.unlocked == {"first_nuke"}
    assert again.evaluate(_stats(nuke_uses=1)) == []
    assert json.loads(path.read_text())["achievements"] == ["first_nuke"]


def test_foreign_achievements_key_falls_back_to_empty(tmp_path):
    path = tmp_path / "game_save.json"
    path.write_text(json.dumps({"achievements": "nope", "high_score": 7}))
    assert load_unlocked(path) == set()
    path.write_text(
        json.dumps({"achievements": ["first_nuke", "bogus", 42, None]})
    )
    assert load_unlocked(path) == {"first_nuke"}


def test_score_crossing_after_an_unlock_keeps_the_achievements_key(tmp_path):
    """The designed tripwire, real sequence: Score writes on every high-score
    crossing, and its write used to flush the construction-time snapshot —
    erasing the achievements key this feature wrote after construction."""
    path = tmp_path / "game_save.json"
    game, player, asteroids, shots, field, economy = make_world(tmp_path)
    achievements = Achievements(save_path=path)

    achievements.evaluate(_stats(nuke_uses=1))  # unlock first: file gains the key
    economy.credits = 250.0
    economy.save()  # the idle ledger's keys join the file
    assert load_unlocked(path) == {"first_nuke"}

    game.add_score(50)  # beats the fresh high score: Score rewrites the file

    assert load_unlocked(path) == {"first_nuke"}, "Score's write clobbered the key"
    merged = json.loads(path.read_text())
    assert merged["high_score"] == 50
    assert merged["idle_credits"] == 250.0  # the economy's keys ride along too


def test_mute_and_volume_writes_after_an_unlock_keep_the_key_too(tmp_path):
    path = tmp_path / "game_save.json"
    achievements = Achievements(save_path=path)
    achievements.evaluate(_stats(nuke_uses=1))

    score = Score(save_path=path)
    score.set_muted(True)
    score.set_volume(40)

    assert load_unlocked(path) == {"first_nuke"}


# --- the live wiring: snapshot builder, restart hooks, game-over gating -------


def make_world(tmp_path):
    """Fresh groups + Game + field + economy wired like main(), saving into
    tmp_path (the test_stats.make_world pattern)."""
    updatable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    asteroids_drawable = pygame.sprite.Group()

    Player.containers = (updatable, asteroids_drawable)
    Asteroid.containers = (asteroids, updatable, asteroids_drawable)
    Shot.containers = (shots, updatable, asteroids_drawable)
    AsteroidField.containers = updatable

    player = Player(400, 300)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    economy = Economy(save_path=tmp_path / "game_save.json")
    return game, player, asteroids, shots, field, economy


def test_snapshot_builder_reads_the_live_owners(tmp_path):
    game, player, asteroids, shots, field, economy = make_world(tmp_path)
    economy.credits = 100000.0
    assert economy.buy("drone")
    assert economy.activate_powerup("nuke")
    game.add_score(500)
    game.wave = 6

    stats = event_stats_from(game, economy)
    assert stats == EventStats(
        score=500.0, wave=6, nuke_uses=1, drone_level=1,
        high_score_beaten=True,
    )


def test_score_award_unlocks_and_queues_toasts_in_table_order(tmp_path):
    game, player, asteroids, shots, field, economy = make_world(tmp_path)
    achievements = Achievements(save_path=tmp_path / "game_save.json")

    game.add_score(ACHIEVEMENT_SCORE_THRESHOLD)
    newly = achievements.evaluate(event_stats_from(game, economy))

    # The run's first score crossing also beats the fresh save's high score:
    # two awards on one frame, announced in table order.
    assert [defn.id for defn in newly] == ["score_10000", "high_score_beaten"]
    achievements.update(0.0)
    assert achievements.toasts.current == "SCORE 10,000"
    achievements.toasts.update(TOAST_SECONDS)
    achievements.update(0.0)
    assert achievements.toasts.current == "HIGH SCORE BEATEN"


def test_achievements_survive_both_restart_hooks(tmp_path):
    game, player, asteroids, shots, field, economy = make_world(tmp_path)
    achievements = Achievements(save_path=tmp_path / "game_save.json")
    achievements.evaluate(_stats(nuke_uses=1))
    assert achievements.unlocked == {"first_nuke"}

    # Hook 1: Game.restart. Hook 2: the R-key branch (main.restart_run).
    # The unlocked set is lifetime, so both hooks must leave it alone.
    game.restart()
    assert achievements.unlocked == {"first_nuke"}
    restart_run(game, economy, field, WaveBanner(), asteroids)
    assert achievements.unlocked == {"first_nuke"}
    assert achievements.evaluate(event_stats_from(game, economy)) == []


# --- the headless render -------------------------------------------------------


def test_toast_render_smoke_headless():
    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    screen = pygame.display.get_surface()

    queue = ToastQueue()
    queue.update(0.0)  # seat the one queued toast
    screen.fill(PALETTE["paper"])
    queue.draw(screen)  # smoke: empty queue draws nothing, raises nothing

    queue.show("HIGH SCORE BEATEN")
    queue.update(0.0)
    queue.update(TOAST_SLIDE_SECONDS)  # fully seated
    screen.fill(PALETTE["paper"])
    queue.draw(screen)
    # The seat region holds the panel, not the paper background.
    seat = screen.get_at((SCREEN_WIDTH // 2, TOAST_SEAT_Y + 10))[:3]
    assert seat != PALETTE["paper"]
