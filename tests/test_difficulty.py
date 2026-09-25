"""Tier 2 difficulty modes: the mode table, the mode-aware wave_params,
the per-mode lives, the persisted selection, and the start/game-over
flow's select lines. Pure tests pin the table math; the persistence and
selection tests drive Score/Game directly over tmp_path saves, the same
way the save and restart tests do.
"""

import json

import pygame
import pytest

from asteroidfield import wave_params
from constants import (
    DIFFICULTY_KEY_LABELS,
    DIFFICULTY_MODES,
    DIFFICULTY_SELECT_KEYS,
    DIFFICULTY_TABLE,
    PLAYER_START_LIVES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    WAVE_SPAWN_INTERVAL_FLOOR,
)
from game import Game, mode_lives
from hud import Score, game_over_lines, mode_menu_lines
from player import Player


class TestDifficultyTable:
    def test_exactly_three_modes_named_easy_normal_hard(self):
        assert DIFFICULTY_MODES == ("easy", "normal", "hard")

    def test_easy_starts_with_five_lives(self):
        assert DIFFICULTY_TABLE["easy"]["lives"] == 5

    def test_hard_starts_with_two_lives(self):
        assert DIFFICULTY_TABLE["hard"]["lives"] == 2

    def test_normal_is_the_shipped_tuning(self):
        cfg = DIFFICULTY_TABLE["normal"]
        assert cfg["lives"] == PLAYER_START_LIVES
        assert cfg["spawn_interval_mult"] == 1.0
        assert cfg["speed_mult"] == 1.0

    def test_multipliers_bend_both_directions_around_normal(self):
        easy = DIFFICULTY_TABLE["easy"]
        normal = DIFFICULTY_TABLE["normal"]
        hard = DIFFICULTY_TABLE["hard"]
        assert easy["spawn_interval_mult"] > normal["spawn_interval_mult"]
        assert hard["spawn_interval_mult"] < normal["spawn_interval_mult"]
        assert easy["speed_mult"] < normal["speed_mult"] < hard["speed_mult"]

    def test_every_row_carries_a_menu_blurb(self):
        for mode in DIFFICULTY_MODES:
            blurb = DIFFICULTY_TABLE[mode]["blurb"]
            assert isinstance(blurb, str) and blurb

    def test_select_keys_map_one_two_three_to_the_modes(self):
        assert {key for key in DIFFICULTY_SELECT_KEYS} == {49, 50, 51}
        assert set(DIFFICULTY_SELECT_KEYS.values()) == set(DIFFICULTY_MODES)
        assert set(DIFFICULTY_KEY_LABELS.values()) == {"1", "2", "3"}


class TestWaveParamsByMode:
    def test_wave_one_normal_matches_the_shipped_tuning(self):
        params = wave_params(1)
        assert params["speed_min"] == 40
        assert params["speed_max"] == 100

    def test_wave_one_easy_is_slower_than_normal(self):
        easy = wave_params(1, "easy")
        normal = wave_params(1, "normal")
        assert easy["speed_min"] < normal["speed_min"]
        assert easy["speed_max"] < normal["speed_max"]

    def test_wave_one_hard_is_faster_than_normal(self):
        hard = wave_params(1, "hard")
        normal = wave_params(1, "normal")
        assert hard["speed_min"] > normal["speed_min"]
        assert hard["speed_max"] > normal["speed_max"]

    def test_wave_one_easy_spawns_less_often_than_normal(self):
        easy = wave_params(1, "easy")["spawn_interval"]
        normal = wave_params(1, "normal")["spawn_interval"]
        assert easy > normal

    def test_wave_one_hard_spawns_more_often_than_normal(self):
        hard = wave_params(1, "hard")["spawn_interval"]
        normal = wave_params(1, "normal")["spawn_interval"]
        assert hard < normal

    def test_easy_intervals_never_tighten_across_waves(self):
        intervals = [wave_params(w, "easy")["spawn_interval"] for w in range(1, 16)]
        assert all(late <= early for early, late in zip(intervals, intervals[1:]))
        assert intervals[-1] >= WAVE_SPAWN_INTERVAL_FLOOR

    def test_easy_is_never_tighter_than_hard_at_any_wave(self):
        for wave in range(1, 16):
            easy = wave_params(wave, "easy")["spawn_interval"]
            hard = wave_params(wave, "hard")["spawn_interval"]
            assert easy >= hard

    def test_easy_speeds_stay_under_hard_speeds_at_every_wave(self):
        for wave in range(1, 16):
            easy = wave_params(wave, "easy")
            hard = wave_params(wave, "hard")
            assert easy["speed_min"] < hard["speed_min"]
            assert easy["speed_max"] < hard["speed_max"]

    def test_speeds_are_integers_for_the_field_randint(self):
        for mode in DIFFICULTY_MODES:
            for wave in (1, 3, 7):
                params = wave_params(wave, mode)
                assert isinstance(params["speed_min"], int)
                assert isinstance(params["speed_max"], int)

    def test_unknown_mode_raises_rather_than_silently_defaulting(self):
        with pytest.raises(KeyError):
            wave_params(1, "impossible")


def test_mode_lives_table():
    assert mode_lives("easy") == 5
    assert mode_lives("normal") == 3
    assert mode_lives("hard") == 2


class TestScoreModePersistence:
    def test_fresh_save_defaults_to_normal(self, tmp_path):
        score = Score(tmp_path / "save.json")
        assert score.mode == "normal"

    def test_set_mode_persists_through_the_save_merge(self, tmp_path):
        path = tmp_path / "save.json"
        Score(path).set_mode("hard")
        again = Score(path)
        assert again.mode == "hard"

    def test_set_mode_rejects_unknown_modes(self, tmp_path):
        score = Score(tmp_path / "save.json")
        with pytest.raises(ValueError):
            score.set_mode("impossible")

    def test_high_score_is_tracked_per_mode(self, tmp_path):
        path = tmp_path / "save.json"
        run_one = Score(path)
        run_one.add_score(1500)  # a Normal run's final total
        run_one.set_mode("easy")  # the next run selects Easy

        run_two = Score(path)  # a fresh run reads the retargeted best
        assert run_two.high == 0
        run_two.add_score(500)
        assert run_two.high == 500

        highs = Score(path).mode_highs
        assert highs["normal"] == 1500
        assert highs["easy"] == 500
        assert highs["hard"] == 0

    def test_modes_do_not_cross_contaminate(self, tmp_path):
        path = tmp_path / "save.json"
        normal_run = Score(path)
        normal_run.add_score(999)
        normal_run.set_mode("hard")

        hard_run = Score(path)
        assert hard_run.high == 0
        assert not hard_run.beaten  # a fresh comparison, re-armed
        hard_run.add_score(100)
        assert hard_run.high == 100  # Normal's 999 did not leak into Hard

    def test_legacy_high_score_key_still_tracks_the_overall_best(self, tmp_path):
        path = tmp_path / "save.json"
        normal_run = Score(path)
        normal_run.add_score(2000)  # Normal — beats the legacy key
        normal_run.set_mode("easy")
        easy_run = Score(path)  # the Easy run starts from its own best
        easy_run.add_score(300)  # worse — must not lower the legacy key
        data = json.loads(path.read_text())
        assert data["high_score"] == 2000
        assert data["high_score_easy"] == 300
        assert data["high_score_normal"] == 2000

    def test_missing_normal_record_seeds_from_the_legacy_key(self, tmp_path):
        path = tmp_path / "save.json"
        path.write_text(json.dumps({"high_score": 4200, "muted": False}))
        score = Score(path)
        assert score.high == 4200
        assert score.mode_highs["normal"] == 4200
        assert score.mode_highs["easy"] == 0


class TestMenuAndGameOverLines:
    def test_menu_rows_cover_every_mode_in_table_order(self):
        rows = mode_menu_lines("normal", {"easy": 10, "normal": 200, "hard": 0})
        assert len(rows) == 3
        assert "EASY" in rows[0]
        assert "NORMAL" in rows[1]
        assert "HARD" in rows[2]
        assert "best 10" in rows[0]
        assert "best 200" in rows[1]
        assert "best 0" in rows[2]

    def test_menu_rows_mark_exactly_the_saved_choice(self):
        rows = mode_menu_lines("hard", {})
        assert "< saved" in rows[2]
        assert sum("< saved" in row for row in rows) == 1

    def test_menu_rows_carry_each_mode_blurb(self):
        for row, mode in zip(mode_menu_lines("normal", {}), DIFFICULTY_MODES):
            assert DIFFICULTY_TABLE[mode]["blurb"] in row

    def test_game_over_prompt_offers_the_select_when_a_mode_is_known(self):
        lines = game_over_lines(500, False, "hard")
        assert lines[-1] == "R restart - 1/2/3 mode (HARD) - Q quit"

    def test_game_over_prompt_is_unchanged_without_a_mode(self):
        lines = game_over_lines(500, False)
        assert lines == ["Game over — score 500", "press R to restart, Q to quit"]

    def test_game_over_stays_three_lines_with_high_score_and_mode(self):
        lines = game_over_lines(900, True, "easy")
        assert len(lines) == 3
        assert lines[1] == "New high score!"


def _dummy_game(tmp_path):
    """A real Game wired like the low-lives fixture — a real Player, so
    restart's clear_powerups/respawn path runs for real."""
    pygame.init()
    empty = pygame.sprite.Group()
    Player.containers = ()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    return Game(player, empty, empty, save_path=tmp_path / "save.json")


class TestSelectFlow:
    def test_set_mode_persists_and_applies_on_restart(self, tmp_path):
        game = _dummy_game(tmp_path)
        game.set_mode("hard")
        assert game.lives == 3  # selection never lands mid-run
        game.lives = 99  # a worn run's lives
        game.restart()
        assert game.lives == 2  # the new mode applies at restart

        reborn = _dummy_game(tmp_path)
        assert reborn.mode == "hard"  # the persisted choice resumed
        assert reborn.lives == 2

    def test_easy_run_starts_with_five_lives(self, tmp_path):
        game = _dummy_game(tmp_path)
        game.set_mode("easy")
        game.restart()
        assert game.lives == 5

    def test_restart_keeps_the_current_mode(self, tmp_path):
        game = _dummy_game(tmp_path)
        game.set_mode("easy")
        game.restart()
        game.set_mode("normal")
        game.restart()
        assert game.mode == "normal"
        assert game.lives == 3
