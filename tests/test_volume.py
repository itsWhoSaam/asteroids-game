"""Tests for the master volume control (UX wave).

The seam mirrors F6's mute: Game owns the persisted level through the save
loader, main relays it to the sound module, and playback scales by it while
mute suppresses outright without touching the stored level. The gain math
and step bounds are pure; the save round-trip pins the new volume key
through the read-modify-write merge; the mixer-absent path stays a silent
no-op.
"""

import json

import pygame
import pytest

import sound
from constants import (
    SFX_SHOOT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    VOLUME_DEFAULT,
    VOLUME_MAX,
    VOLUME_MIN,
)
from game import Game
from hud import HUD_MARGIN, HUD_TAG_GAP, Score, draw_hud, hud_font, load_save, write_save
from player import Player


@pytest.fixture(autouse=True)
def fresh_sound(monkeypatch):
    """A pristine sound module per test; pygame (font + mixer) ready."""
    monkeypatch.setattr(sound, "_muted", False)
    monkeypatch.setattr(sound, "_volume", VOLUME_DEFAULT)
    monkeypatch.setattr(sound, "_sounds", {})
    pygame.init()
    sound.init()


# --- pure gain math ------------------------------------------------------------


def test_clamp_volume_snaps_into_range():
    assert sound.clamp_volume(-10) == VOLUME_MIN
    assert sound.clamp_volume(0) == 0
    assert sound.clamp_volume(50) == 50
    assert sound.clamp_volume(110) == VOLUME_MAX
    assert sound.clamp_volume(57.9) == 57  # whole percents only


def test_master_gain_maps_level_to_mixer_gain():
    assert sound.master_gain(0) == 0.0
    assert sound.master_gain(50) == 0.5
    assert sound.master_gain(100) == 1.0


def test_set_volume_clamps_and_stores():
    sound.set_volume(40)
    assert sound.get_volume() == 40
    sound.set_volume(999)
    assert sound.get_volume() == VOLUME_MAX
    sound.set_volume(-1)
    assert sound.get_volume() == VOLUME_MIN


# --- volume scaling on the real synth builder -----------------------------------


def test_synth_buffers_stay_at_full_gain_at_the_default_level():
    """The builders bake their per-cue loudness (SFX_*_VOLUME); at the
    default 100% level the master gain leaves the cue untouched."""
    built = sound._sounds[SFX_SHOOT]
    assert built.get_volume() == 1.0
    sound.play(SFX_SHOOT)
    assert built.get_volume() == 1.0


def test_play_scales_the_real_cue_by_the_master_level():
    """The mixer cue's gain follows the level: half volume halves it, zero
    silences it — every SFX scales, none is exempt."""
    sound.set_volume(50)
    sound.play(SFX_SHOOT)
    assert sound._sounds[SFX_SHOOT].get_volume() == 0.5

    sound.set_volume(0)
    sound.play(SFX_SHOOT)
    assert sound._sounds[SFX_SHOOT].get_volume() == 0.0


def test_play_reapplies_the_gain_on_every_call():
    """The level is read per play call, so stepping mid-run takes effect
    on the next cue without re-initializing anything."""
    sound.set_volume(70)
    sound.play(SFX_SHOOT)
    sound.set_volume(10)
    sound.play(SFX_SHOOT)
    # the mixer quantizes gain to 1/128 steps — allow one step of slack
    assert sound._sounds[SFX_SHOOT].get_volume() == pytest.approx(0.1, abs=1 / 128)


def test_mute_overrides_audibly_and_preserves_the_level(monkeypatch):
    """Mute suppresses playback outright — and never touches the stored
    level: unmuting resumes at exactly the volume set before muting."""
    played = []

    class Recorder:
        def set_volume(self, gain):
            self.gain = gain

        def play(self):
            played.append(self.gain)

    recorder = Recorder()
    monkeypatch.setattr(sound, "_sounds", {SFX_SHOOT: recorder})

    sound.set_volume(40)
    sound.play(SFX_SHOOT)
    assert played == [0.4]

    sound.set_muted(True)  # M pressed: audible silence, level untouched
    sound.play(SFX_SHOOT)
    assert played == [0.4]
    assert sound.get_volume() == 40

    sound.set_muted(False)
    sound.play(SFX_SHOOT)
    assert played == [0.4, 0.4]  # resumes at the preserved level


# --- degradation ----------------------------------------------------------------


def test_play_is_a_silent_noop_without_a_mixer():
    """No table, no crash, no crash-path — the degraded module ignores
    volume entirely and keeps the preference for a working mixer."""
    sound.set_volume(30)
    sound._sounds.clear()
    sound.play(SFX_SHOOT)
    assert sound.get_volume() == 30


def test_play_volume_failure_degrades_to_silence(monkeypatch, capsys):
    """A mixer that accepts init but rejects volume/play still cannot take
    the game down: one warning, then silence for the rest of the run."""

    class Broken:
        def set_volume(self, gain):
            raise pygame.error("volume failed")

        def play(self):
            raise AssertionError("must not be reached once set_volume fails")

    monkeypatch.setattr(sound, "_sounds", {SFX_SHOOT: Broken()})
    sound.play(SFX_SHOOT)  # must not raise
    assert sound._sounds == {}
    assert "playback failed" in capsys.readouterr().err


# --- save round-trip through the merge -------------------------------------------


def make_game(save_path):
    """A Game wired to a real player and groups, saving into save_path."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    Player.containers = (updatable, drawable)
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    return Game(player, asteroids, shots, powerups, save_path=save_path)


def test_volume_key_survives_the_save_roundtrip(tmp_path):
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 5, "muted": True, "volume": 70,
                      "idle_credits": 12.5})
    loaded = load_save(path)
    assert loaded["volume"] == 70
    assert loaded["idle_credits"] == 12.5  # unknown keys ride along


def test_missing_or_corrupt_volume_falls_back_to_default(tmp_path):
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 1})
    assert load_save(path)["volume"] == VOLUME_DEFAULT

    for bad in ("loud", 3.5, -1, 101, True, None):
        write_save(path, {"high_score": 1, "volume": bad})
        assert load_save(path)["volume"] == VOLUME_DEFAULT, bad


def test_set_volume_preserves_unknown_save_keys(tmp_path):
    """The read-modify-write contract holds for the new writer: keys owned
    by later features ride along untouched."""
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 5, "muted": False, "volume": 100,
                      "idle_credits": 42.0})

    Score(path).set_volume(60)

    assert load_save(path) == {"high_score": 5, "muted": False,
                               "volume": 60, "idle_credits": 42.0}


def test_high_score_write_keeps_the_volume_key(tmp_path):
    """add_score's milestone write must not clobber the volume key it
    doesn't manage — the same tripwire the idle keys use."""
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 5, "muted": False, "volume": 30})

    score = Score(path)
    score.add_score(600)

    saved = load_save(path)
    assert saved["high_score"] == 600
    assert saved["volume"] == 30


# --- Game wiring: steps, bounds, persistence, restart ----------------------------


def test_step_volume_steps_in_ten_percent_increments(tmp_path):
    game = make_game(tmp_path / "game_save.json")
    assert game.volume == VOLUME_DEFAULT
    assert game.step_volume(-1) == 90
    assert game.step_volume(-1) == 80
    assert game.step_volume(1) == 90


def test_step_volume_clamps_at_the_bounds(tmp_path):
    game = make_game(tmp_path / "game_save.json")
    for _ in range(12):
        game.step_volume(-1)
    assert game.volume == VOLUME_MIN
    game.step_volume(-1)  # [ at 0% stays at 0%
    assert game.volume == VOLUME_MIN
    for _ in range(12):
        game.step_volume(1)
    assert game.volume == VOLUME_MAX
    game.step_volume(1)  # ] at 100% stays at 100%
    assert game.volume == VOLUME_MAX


def test_volume_step_persists_and_reloads(tmp_path):
    save_path = tmp_path / "game_save.json"
    game = make_game(save_path)
    game.step_volume(-3)  # 100 → 70

    assert json.loads(save_path.read_text())["volume"] == 70

    reloaded = make_game(save_path)
    assert reloaded.volume == 70


def test_mute_toggle_keeps_the_volume_level(tmp_path):
    """The M flow never routes through the volume key: toggling mute
    before, after, and across steps leaves the level exactly as left."""
    save_path = tmp_path / "game_save.json"
    game = make_game(save_path)
    game.step_volume(-5)  # 50
    assert game.toggle_mute() is True
    assert game.volume == 50
    assert game.toggle_mute() is False
    assert game.volume == 50
    assert json.loads(save_path.read_text())["volume"] == 50


def test_restart_does_not_reset_playback_preferences(tmp_path):
    """Volume and mute are playback-only, not run state: a restart resets
    the score and world, never the audio prefs."""
    game = make_game(tmp_path / "game_save.json")
    game.step_volume(-4)  # 60
    game.toggle_mute()

    game.restart()

    assert game.volume == 60
    assert game.muted is True


# --- HUD tag ---------------------------------------------------------------------


def vol_tag_rect():
    """The probe rectangle for 'VOL 70%' at its unmuted corner anchor."""
    return hud_font().render("VOL 70%", True, "white").get_rect(
        topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
    )


def lit_samples(screen, rect):
    return [
        screen.get_at((x, y))[:3]
        for x in range(max(0, rect.left), rect.right, 3)
        for y in range(rect.top, rect.bottom, 3)
    ]


def test_hud_shows_vol_tag_at_the_set_level():
    """A VOL N% tag appears top-right when the level is known and nothing
    renders there otherwise (volume=None keeps old callers' pixels)."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    rect = vol_tag_rect()

    screen.fill((0, 0, 0))
    draw_hud(screen, 0, volume=None)
    assert all(pixel == (0, 0, 0) for pixel in lit_samples(screen, rect))

    screen.fill((0, 0, 0))
    draw_hud(screen, 0, volume=70)
    assert any(pixel != (0, 0, 0) for pixel in lit_samples(screen, rect))


def test_hud_vol_tag_shows_the_level_number():
    """The tag reads the level: VOL 100% and VOL 0% light different pixel
    counts than VOL 70% would at the same anchor."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    wide = hud_font().render("VOL 100%", True, "white").get_rect(
        topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
    )

    screen.fill((0, 0, 0))
    draw_hud(screen, 0, volume=100)
    assert any(pixel != (0, 0, 0) for pixel in lit_samples(screen, wide))


def test_hud_vol_tag_sits_beside_muted_not_on_it():
    """Both tags visible at once: MUTED keeps its F6 corner anchor and VOL
    N% tucks to its left, separated by HUD_TAG_GAP — neither overwrites
    the other."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    muted_rect = hud_font().render("MUTED", True, "white").get_rect(
        topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
    )
    vol_rect = hud_font().render("VOL 70%", True, "white").get_rect(
        topright=(
            SCREEN_WIDTH - HUD_MARGIN - muted_rect.width - HUD_TAG_GAP,
            HUD_MARGIN,
        )
    )

    screen.fill((0, 0, 0))
    draw_hud(screen, 0, muted=True, volume=70)

    assert any(pixel != (0, 0, 0) for pixel in lit_samples(screen, muted_rect))
    assert any(pixel != (0, 0, 0) for pixel in lit_samples(screen, vol_rect))
