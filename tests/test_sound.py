"""Tests for procedural sound effects and the mute toggle (engagement F6).

The failure-safety contract is the load-bearing part: a missing or broken
mixer degrades the whole module to a silent no-op — the game never crashes
over audio. Everything else pins the synthesis format (stereo signed 16-bit
at CD rate), the tier routing, and the mute persistence through the save
loader.
"""

import json

import pygame
import pytest

import sound
from asteroid import Asteroid
from constants import (
    SFX_CHANNELS,
    SFX_EXPLOSION_LARGE,
    SFX_EXPLOSION_MEDIUM,
    SFX_EXPLOSION_SMALL,
    SFX_FORMAT,
    SFX_GAME_OVER,
    SFX_POWERUP,
    SFX_SAMPLE_RATE,
    SFX_SHOOT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import Game
from hud import HUD_MARGIN, Score, draw_hud, hud_font, load_save, write_save
from main import handle_collisions
from player import Player
from shot import Shot


@pytest.fixture(autouse=True)
def fresh_sound(monkeypatch):
    """A pristine sound module per test; pygame (font + mixer) ready."""
    monkeypatch.setattr(sound, "_muted", False)
    monkeypatch.setattr(sound, "_sounds", {})
    pygame.init()
    sound.init()


def make_groups():
    """Fresh groups with class containers wired, mirroring main()."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    powerups = pygame.sprite.Group()

    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)

    return updatable, drawable, asteroids, shots, powerups


# --- init & buffer format -----------------------------------------------------


def test_mixer_initializes_at_the_documented_format():
    """The dummy audio driver still gives a real mixer at CD quality,
    stereo, signed 16-bit — the session-probe contract F6 builds on."""
    assert pygame.mixer.get_init() == (SFX_SAMPLE_RATE, SFX_FORMAT, SFX_CHANNELS)


def test_init_builds_every_named_cue():
    assert set(sound._sounds) == {
        SFX_SHOOT,
        SFX_EXPLOSION_SMALL,
        SFX_EXPLOSION_MEDIUM,
        SFX_EXPLOSION_LARGE,
        SFX_POWERUP,
        SFX_GAME_OVER,
    }
    sound.init()  # idempotent: a second call must not rebuild or crash
    assert set(sound._sounds)  # still populated


@pytest.mark.parametrize(
    "name, min_duration",
    [
        (SFX_SHOOT, 0.05),
        (SFX_EXPLOSION_SMALL, 0.1),
        (SFX_EXPLOSION_MEDIUM, 0.2),
        (SFX_EXPLOSION_LARGE, 0.3),
        (SFX_POWERUP, 0.1),
        (SFX_GAME_OVER, 0.5),
    ],
)
def test_every_sfx_is_a_nonempty_sound_in_mixer_format(name, min_duration):
    """Each builder wraps real samples: non-empty raw buffer, whole stereo
    s16 frames, and a duration in the right neighborhood for the cue."""
    built = sound._sounds[name]
    assert isinstance(built, pygame.mixer.Sound)
    raw = built.get_raw()
    assert len(raw) > 0
    bytes_per_frame = SFX_CHANNELS * 2  # stereo, signed 16-bit
    assert len(raw) % bytes_per_frame == 0
    duration = len(raw) / bytes_per_frame / SFX_SAMPLE_RATE
    assert min_duration <= duration < 1.5  # every cue is short


def test_explosion_tiers_have_distinct_buffers_and_pitch_order():
    """Three pitches keyed to size: distinct buffers, and the big rock's
    rumble lasts longer than the small rock's crack."""
    raws = [
        sound._sounds[SFX_EXPLOSION_SMALL].get_raw(),
        sound._sounds[SFX_EXPLOSION_MEDIUM].get_raw(),
        sound._sounds[SFX_EXPLOSION_LARGE].get_raw(),
    ]
    assert len(set(raws)) == 3
    assert len(raws[0]) < len(raws[1]) < len(raws[2])


# --- playback guards ----------------------------------------------------------


def test_play_respects_mute(monkeypatch):
    played = []

    class Recorder:
        def play(self):
            played.append(True)

    monkeypatch.setattr(sound, "_sounds", {SFX_SHOOT: Recorder()})

    sound.set_muted(False)
    sound.play(SFX_SHOOT)
    assert played == [True]

    sound.set_muted(True)  # suppression only — no error, no playback
    sound.play(SFX_SHOOT)
    assert played == [True]


def test_play_unknown_name_is_a_noop():
    sound.play("does_not_exist")  # must not raise


def test_play_is_a_noop_when_the_table_is_empty():
    """No mixer, no table, no crash — the degraded module stays silent."""
    sound._sounds.clear()
    sound.play(SFX_SHOOT)


def test_init_failure_degrades_to_silent_noop(monkeypatch, capsys):
    """Mixer init mocked to fail: the module runs silent — no exception,
    an empty table, and a warning on stderr instead of a swallowed error."""

    def broken(*args, **kwargs):
        raise pygame.error("no audio device")

    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    monkeypatch.setattr(pygame.mixer, "init", broken)

    sound._sounds = {}  # simulate the very first init (the fixture filled it)
    sound.init()  # must not raise

    assert sound._sounds == {}
    assert "mixer unavailable" in capsys.readouterr().err
    sound.play(SFX_SHOOT)  # no-op path


def test_game_runs_with_broken_mixer(monkeypatch, tmp_path):
    """The full destruction and game-over paths run to completion with a
    dead mixer — audio failure can never take the game down (spec gate)."""

    def broken(*args, **kwargs):
        raise pygame.error("no audio device")

    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    monkeypatch.setattr(pygame.mixer, "init", broken)
    sound._sounds.clear()

    updatable, drawable, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")

    Shot(player.position.x, player.position.y)
    Asteroid(player.position.x, player.position.y, 60)  # overlapping: dies
    handle_collisions(asteroids, shots, player, game, powerups)
    assert game.score > 0  # destruction resolved normally, no audio crash

    game.lives = 1
    game.player_hit()  # the real game-over path fires its sfx through play()
    assert game.state == "game_over"


# --- wiring: the call sites fire the right cue --------------------------------


def test_shoot_plays_the_shoot_cue_once(monkeypatch):
    """One blip per trigger pull — even a TRIPLE volley stays one sound."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    updatable, drawable, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)

    player.shoot()

    assert played == [SFX_SHOOT]


def test_game_over_plays_the_end_cue(monkeypatch, tmp_path):
    """The game-over path is where the descending tone fires — hits before
    that (respawns) stay silent by design."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    updatable, drawable, asteroids, shots, powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, powerups,
                save_path=tmp_path / "game_save.json")

    game.player_hit()  # a respawn, not a run end: no cue
    game.lives = 1
    game.player_hit()  # zero lives: the game-over cue fires

    assert played == [SFX_GAME_OVER]


# --- mute persistence through the save loader ---------------------------------


def test_mute_toggle_persists_through_the_save_loader(tmp_path):
    """M flips the preference and writes it via the save loader; a fresh
    Game reads it back (roundtrip on tmp_path)."""
    updatable, drawable, asteroids, shots, powerups = make_groups()
    save_path = tmp_path / "game_save.json"
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, powerups, save_path=save_path)

    assert game.muted is False
    assert game.toggle_mute() is True
    assert game.muted is True

    saved = json.loads(save_path.read_text())
    assert saved["muted"] is True

    reloaded = Game(player, asteroids, shots, powerups, save_path=save_path)
    assert reloaded.muted is True
    assert reloaded.toggle_mute() is False
    assert load_save(save_path)["muted"] is False


def test_set_muted_preserves_unknown_save_keys(tmp_path):
    """The read-modify-write contract holds through the new method: keys
    owned by later features ride along untouched."""
    path = tmp_path / "game_save.json"
    write_save(path, {"high_score": 5, "muted": False, "coins": 9})

    score = Score(path)
    score.set_muted(True)

    assert load_save(path) == {"high_score": 5, "muted": True, "coins": 9}


# --- HUD indicator ------------------------------------------------------------


def test_hud_shows_muted_indicator_only_while_muted():
    """A MUTED tag appears top-right while muted and nowhere otherwise."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    rect = hud_font().render("MUTED", True, "white").get_rect(
        topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
    )

    def lit_samples(muted):
        screen.fill("black")
        draw_hud(screen, 0, muted=muted)
        return [
            screen.get_at((x, y))
            for x in range(max(0, rect.left), rect.right, 4)
            for y in range(rect.top, rect.bottom, 4)
        ]

    assert all(pixel == (0, 0, 0, 255) for pixel in lit_samples(muted=False))
    assert any(pixel != (0, 0, 0, 255) for pixel in lit_samples(muted=True))
