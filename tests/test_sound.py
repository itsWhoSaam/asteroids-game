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
from asteroidfield import AsteroidField
from constants import (
    PALETTE,
    SFX_CHANNELS,
    SFX_COMBO_BREAK,
    SFX_CURSE,
    SFX_DASH,
    SFX_DENIED,
    SFX_DENIED_GAP_S,
    SFX_DENIED_THUD_S,
    SFX_DRONE_FIRE,
    SFX_EXPLOSION_LARGE,
    SFX_EXPLOSION_MEDIUM,
    SFX_EXPLOSION_SMALL,
    SFX_FORMAT,
    SFX_GAME_OVER,
    SFX_POWERUP,
    SFX_SAMPLE_RATE,
    SFX_SAUCER,
    SFX_BLACKHOLE,
    SFX_BOSS,
    SFX_SHOOT,
    SFX_WAVE_CLEAR,
    SFX_WAVE_CLEAR_ARPEGGIO,
    SFX_WAVE_CLEAR_NOTE_S,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from drones import DroneTurret
from economy import Economy
from game import Game
from hud import HUD_MARGIN, Score, WaveBanner, draw_hud, hud_font, load_save, write_save
from main import handle_collisions, maybe_advance_wave
from player import Player
from shot import Shot
from shop import Shop


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
        SFX_DASH,
        SFX_COMBO_BREAK,
        SFX_SAUCER,
        SFX_BOSS,
        SFX_BLACKHOLE,
        SFX_CURSE,
        SFX_DRONE_FIRE,
        SFX_DENIED,
        SFX_WAVE_CLEAR,
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
        (SFX_DASH, 0.1),
        (SFX_COMBO_BREAK, 0.3),
        (SFX_DRONE_FIRE, 0.05),
        (SFX_DENIED, 0.1),
        (SFX_WAVE_CLEAR, 0.2),
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
        def set_volume(self, gain):
            self.gain = gain  # playback now scales by the master level first

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

    # volume backfills to its default on load, exactly like high_score/muted
    assert load_save(path) == {"high_score": 5, "muted": True, "volume": 100,
                               "coins": 9}


# --- HUD indicator ------------------------------------------------------------


def test_hud_shows_muted_indicator_only_while_muted():
    """A MUTED tag appears top-right while muted and nowhere otherwise."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    rect = hud_font().render("MUTED", True, PALETTE["hud_ink"]).get_rect(
        topright=(SCREEN_WIDTH - HUD_MARGIN, HUD_MARGIN)
    )

    def lit_samples(muted):
        screen.fill(PALETTE["paper"])
        draw_hud(screen, 0, muted=muted)
        return [
            screen.get_at((x, y))
            for x in range(max(0, rect.left), rect.right, 4)
            for y in range(rect.top, rect.bottom, 4)
        ]

    assert all(
        pixel == (*PALETTE["paper"], 255) for pixel in lit_samples(muted=False)
    )
    assert any(
        pixel != (*PALETTE["paper"], 255) for pixel in lit_samples(muted=True)
    )


# --- extra SFX (UX wave): deterministic buffers and wiring ---------------------


@pytest.mark.parametrize(
    "builder",
    [sound.build_drone_fire, sound.build_denied, sound.build_wave_clear],
    ids=["drone_fire", "denied", "wave_clear"],
)
def test_extra_cue_buffers_are_deterministic(builder):
    """The new builders are pure math — no RNG — so rebuilding a cue
    reproduces the exact bytes, same sounds every run and in tests."""
    assert builder().get_raw() == builder().get_raw()


def test_denied_buzz_is_two_thuds_with_a_gap():
    """The buzz's gate is on-off-on across the cue: two thuds separated by
    silence, exactly the double-thud read."""
    thud_s, gap_s = SFX_DENIED_THUD_S, SFX_DENIED_GAP_S
    sample = 1 / SFX_SAMPLE_RATE
    span = 2 * thud_s + gap_s

    assert sound.denied_thud_gain(0.0, thud_s, gap_s) == 1.0
    assert sound.denied_thud_gain(thud_s - sample, thud_s, gap_s) == 1.0
    assert sound.denied_thud_gain(thud_s + gap_s / 2, thud_s, gap_s) == 0.0
    assert sound.denied_thud_gain(thud_s + gap_s, thud_s, gap_s) == 1.0
    assert sound.denied_thud_gain(span - sample, thud_s, gap_s) == 1.0


def test_wave_clear_note_humps_within_each_slot():
    """One attack/decay hump per arpeggio slot: the note starts at zero and
    is loudest mid-slot — no clicks between notes."""
    note_s = SFX_WAVE_CLEAR_NOTE_S
    for slot in range(len(SFX_WAVE_CLEAR_ARPEGGIO)):
        start = slot * note_s
        assert sound.wave_clear_note(start, note_s, SFX_WAVE_CLEAR_ARPEGGIO) == 0.0
        edge = abs(
            sound.wave_clear_note(start + note_s * 0.02, note_s, SFX_WAVE_CLEAR_ARPEGGIO)
        )
        middle = abs(
            sound.wave_clear_note(start + note_s * 0.5, note_s, SFX_WAVE_CLEAR_ARPEGGIO)
        )
        assert middle > edge


def test_wave_clear_arpeggio_rises_slot_to_slot():
    """Zero crossings per slot track the carrier frequency: the jingle climbs
    through the arpeggio instead of droning on one pitch."""
    note_s = SFX_WAVE_CLEAR_NOTE_S
    crossings = []
    for slot in range(len(SFX_WAVE_CLEAR_ARPEGGIO)):
        start = slot * note_s
        samples = [
            sound.wave_clear_note(start + i / SFX_SAMPLE_RATE, note_s, SFX_WAVE_CLEAR_ARPEGGIO)
            for i in range(int(note_s * SFX_SAMPLE_RATE))
        ]
        signs = [1 if s > 0 else -1 for s in samples if s != 0]
        crossings.append(sum(1 for a, b in zip(signs, signs[1:]) if a != b))

    assert crossings == sorted(crossings)
    assert crossings[0] < crossings[-1]


class GainRecorder:
    """A Sound stand-in that logs the master gain and playback count."""

    def __init__(self):
        self.gain = None
        self.played = 0

    def set_volume(self, gain):
        self.gain = gain

    def play(self):
        self.played += 1


def test_drone_fire_plays_its_cue_once_per_shot(monkeypatch):
    """The pew rides the turret's fire event: nothing before the cadence
    fires, one cue at the instant a real Shot joins the group."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    _updatable, _drawable, asteroids, shots, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    turret = DroneTurret(0, 1)

    turret.update(0.7, player, asteroids, shots)  # stagger is 0.75 s: not yet
    assert played == []

    turret.update(0.1, player, asteroids, shots)  # crosses the interval: fires
    assert played == [SFX_DRONE_FIRE]
    assert len(shots) == 1


def test_drone_fire_honors_mute_and_master_volume(monkeypatch):
    """Through the real play() gate: mute suppresses the pew outright, and
    the master level scales its gain — 50% halves it."""
    recorder = GainRecorder()
    monkeypatch.setattr(sound, "_sounds", {SFX_DRONE_FIRE: recorder})
    _updatable, _drawable, asteroids, shots, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    turret = DroneTurret(0, 1)

    sound.set_muted(True)
    turret.fire(player, asteroids, shots)
    assert recorder.played == 0

    sound.set_muted(False)
    sound.set_volume(50)
    turret.fire(player, asteroids, shots)
    assert recorder.played == 1
    assert recorder.gain == pytest.approx(0.5)


def make_shop_world(tmp_path, credits):
    """A Shop on a fresh Economy and Player, the ledger pre-funded or not."""
    _updatable, _drawable, asteroids, shots, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    economy = Economy(save_path=str(tmp_path / "game_save.json"))
    economy.credits = credits
    return Shop(economy, player)


def test_denied_buzz_when_upgrade_is_unaffordable(monkeypatch, tmp_path):
    """A shop key the ledger can't pay buzzes once; the same key once
    affordable completes the purchase and never buzzes."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    shop = make_shop_world(tmp_path, credits=0)

    assert shop.handle_key(pygame.K_1) is None
    assert played == [SFX_DENIED]

    shop.economy.credits = 100_000
    assert shop.handle_key(pygame.K_1) is not None
    assert played == [SFX_DENIED]  # unchanged: success stays quiet


def test_denied_buzz_when_powerup_is_unaffordable(monkeypatch, tmp_path):
    """The bought-powerup path denies with the same buzz — gold_rush at
    zero credits."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    shop = make_shop_world(tmp_path, credits=0)

    assert shop.handle_powerup_key(pygame.K_7) is None
    assert played == [SFX_DENIED]


def test_non_shop_key_never_buzzes(monkeypatch, tmp_path):
    """Movement keys fall through the shop untouched — no denial, no cue."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    shop = make_shop_world(tmp_path, credits=0)

    assert shop.handle_key(pygame.K_w) is None
    assert played == []


def make_wave_world(tmp_path):
    """Fresh Game + AsteroidField wired like main(), per the waves harness."""
    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    Player.containers = (updatable, drawable)
    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = updatable

    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    game = Game(player, asteroids, shots, save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    return game, field


def test_wave_clear_jingle_fires_on_advance(monkeypatch, tmp_path):
    """Clearing a populated field advances the wave and plays the jingle."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    game, field = make_wave_world(tmp_path)
    banner = WaveBanner()

    field.spawn(60, pygame.Vector2(100, 100), pygame.Vector2(10, 0)).kill()
    maybe_advance_wave(game, field, banner)

    assert game.wave == 2
    assert played == [SFX_WAVE_CLEAR]


def test_wave_clear_jingle_stays_quiet_behind_the_populated_guard(
    monkeypatch, tmp_path
):
    """The empty field at game start advances nothing — no jingle for
    wave 1, the guard the waves tests already pin."""
    played = []
    monkeypatch.setattr(sound, "play", lambda name: played.append(name))
    game, field = make_wave_world(tmp_path)
    banner = WaveBanner()

    maybe_advance_wave(game, field, banner)

    assert game.wave == 1
    assert played == []


def test_extra_cue_call_sites_degrade_on_broken_mixer(monkeypatch, tmp_path):
    """Dead mixer: every new call site runs to completion and the module
    stays silent — audio failure can never take the game down."""
    def broken(*args, **kwargs):
        raise pygame.error("no audio device")

    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    monkeypatch.setattr(pygame.mixer, "init", broken)
    sound._sounds = {}

    _updatable, _drawable, asteroids, shots, _powerups = make_groups()
    player = Player(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
    DroneTurret(0, 1).fire(player, asteroids, shots)  # pew path: no crash

    shop = make_shop_world(tmp_path, credits=0)
    assert shop.handle_key(pygame.K_1) is None  # buzz path: no crash

    game = Game(player, asteroids, shots, save_path=tmp_path / "game_save.json")
    field = AsteroidField(game)
    field.spawn(60, pygame.Vector2(100, 100), pygame.Vector2(10, 0)).kill()
    maybe_advance_wave(game, field, WaveBanner())  # jingle path: no crash

    assert game.wave == 2
    assert sound._sounds == {}  # still silent for the rest of the run
