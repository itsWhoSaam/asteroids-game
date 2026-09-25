"""Procedural sound effects and the mute toggle (engagement F6).

Every sound is synthesized at startup from stdlib array/math envelopes and
wrapped in pygame.mixer.Sound — no binary assets, no numpy, no new runtime
dependencies. Failure safety is the contract: if the mixer is unavailable
(headless oddities, exotic machines) the whole module degrades to a silent
no-op — init and every play call are guarded, so audio can never crash the
game. Muting suppresses playback only; the preference itself lives in the
save loader's muted key and reaches this module through set_muted.
"""

import array
import math
import random
import sys

import pygame

from constants import (
    ASTEROID_MIN_RADIUS,
    SFX_BLACKHOLE,
    SFX_BLACKHOLE_BRIGHTNESS,
    SFX_BLACKHOLE_DURATION,
    SFX_BLACKHOLE_SWEEP,
    SFX_BLACKHOLE_VOLUME,
    SFX_BOSS,
    SFX_BOSS_DURATION,
    SFX_BOSS_THUMP_HZ,
    SFX_BOSS_VOLUME,
    SFX_CHANNELS,
    SFX_COMBO_BREAK,
    SFX_COMBO_BREAK_DURATION,
    SFX_COMBO_BREAK_SWEEP,
    SFX_COMBO_BREAK_VOLUME,
    SFX_CURSE,
    SFX_CURSE_DURATION,
    SFX_CURSE_TONES,
    SFX_CURSE_VOLUME,
    SFX_DASH,
    SFX_DASH_BRIGHTNESS,
    SFX_DASH_DURATION,
    SFX_DASH_SWEEP,
    SFX_DASH_VOLUME,
    SFX_DENIED,
    SFX_DENIED_GAP_S,
    SFX_DENIED_HZ,
    SFX_DENIED_THUD_S,
    SFX_DENIED_VOLUME,
    SFX_DRONE_FIRE,
    SFX_DRONE_FIRE_DURATION,
    SFX_DRONE_FIRE_SWEEP,
    SFX_DRONE_FIRE_VOLUME,
    SFX_EXPLOSION_LARGE,
    SFX_EXPLOSION_MEDIUM,
    SFX_EXPLOSION_SMALL,
    SFX_EXPLOSION_TIERS,
    SFX_EXPLOSION_VOLUME,
    SFX_FORMAT,
    SFX_GAME_OVER,
    SFX_GAME_OVER_DURATION,
    SFX_GAME_OVER_SWEEP,
    SFX_GAME_OVER_VOLUME,
    SFX_NOISE_SEED,
    SFX_POWERUP,
    SFX_POWERUP_DURATION,
    SFX_POWERUP_SWEEP,
    SFX_POWERUP_VOLUME,
    SFX_SAMPLE_RATE,
    SFX_SAUCER,
    SFX_SAUCER_DURATION,
    SFX_SAUCER_TONES,
    SFX_SAUCER_VOLUME,
    SFX_SHOOT,
    SFX_SHOOT_DURATION,
    SFX_SHOOT_SWEEP,
    SFX_SHOOT_VOLUME,
    SFX_WAVE_CLEAR,
    SFX_WAVE_CLEAR_ARPEGGIO,
    SFX_WAVE_CLEAR_NOTE_S,
    SFX_WAVE_CLEAR_VOLUME,
    MUSIC_BASS_BEAT_S,
    MUSIC_BASS_HZ,
    MUSIC_BASS_VOLUME,
    MUSIC_GAIN,
    MUSIC_LOOP_SECONDS,
    MUSIC_PAD_A_DETUNE_HZ,
    MUSIC_PAD_A_HZ,
    MUSIC_PAD_B_HZ,
    MUSIC_PAD_VOLUME,
    VOLUME_DEFAULT,
    VOLUME_MAX,
    VOLUME_MIN,
)

# The synthesized SFX table, filled once by init(): name -> mixer.Sound.
# Empty means "audio unavailable" — every play call no-ops.
_sounds = {}
_muted = False
_volume = VOLUME_DEFAULT  # master level 0–100; playback scales by it

# The ambient music loop (Tier 3): built once by init(), None whenever the
# mixer is unavailable — the same degrade contract as the SFX table.
_music = None
_music_on = False       # the gameplay gate: the run wants the loop audible
_music_playing = False  # the loop is actually on the mixer right now


def init():
    """Bring the mixer up and synthesize the SFX table once.

    Any failure leaves the module a silent no-op: the game runs and plays
    nothing. The failure surfaces once as a warning instead of being
    swallowed silently or crashing the run.
    """
    global _sounds, _music
    if _sounds:
        return
    try:
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(SFX_SAMPLE_RATE, SFX_FORMAT, SFX_CHANNELS)
        _sounds = {
            SFX_SHOOT: build_shoot(),
            SFX_EXPLOSION_SMALL: build_explosion("small"),
            SFX_EXPLOSION_MEDIUM: build_explosion("medium"),
            SFX_EXPLOSION_LARGE: build_explosion("large"),
            SFX_POWERUP: build_powerup(),
            SFX_GAME_OVER: build_game_over(),
            # Insanity core (recipes live in the INSANITY constants block):
            SFX_DASH: build_dash(),
            SFX_COMBO_BREAK: build_combo_break(),
            # Insanity threats:
            SFX_SAUCER: build_saucer(),
            SFX_BOSS: build_boss(),
            SFX_BLACKHOLE: build_blackhole(),
            # Insanity chaos:
            SFX_CURSE: build_curse(),
            SFX_DRONE_FIRE: build_drone_fire(),
            SFX_DENIED: build_denied(),
            SFX_WAVE_CLEAR: build_wave_clear(),
        }
        # The loop is the expensive render (~0.4 s): it builds once per
        # process — a rebuilt SFX table keeps the already-built loop.
        if _music is None:
            _music = build_ambient_loop()
    except Exception as exc:
        _sounds = {}
        _music = None
        print(
            f"[sound] warning: mixer unavailable, running silent: {exc}",
            file=sys.stderr,
        )


def set_muted(muted):
    """Playback suppression switch — the game keeps simulating either way."""
    global _muted
    _muted = bool(muted)
    _refresh_music()  # the loop ducking in and out is part of the same switch


def is_muted():
    return _muted


def set_volume(volume):
    """Store the master level (0–100) — the audible scale for every SFX.

    Playback-only preference, the same seam as mute: the persisted copy
    lives in the save loader's volume key and reaches this module through
    this setter. Clamped, never trusted.
    """
    global _volume
    _volume = clamp_volume(volume)
    _refresh_music()  # a live loop re-scales with the step immediately


def get_volume():
    """The current master level, 0–100."""
    return _volume


def clamp_volume(volume):
    """Snap a requested level into the 0–100 range; pure for tests."""
    return max(VOLUME_MIN, min(VOLUME_MAX, int(volume)))


def master_gain(volume):
    """The mixer gain for a level: 100% → 1.0, 0% → silence. Pure."""
    return clamp_volume(volume) / 100.0


def play(name):
    """Play a named SFX scaled by the master volume; a no-op when muted,
    uninitialized, or unknown. Mute overrides audibly — the level survives."""
    if _muted or not _sounds:
        return
    sound = _sounds.get(name)
    if sound is None:
        return
    try:
        sound.set_volume(master_gain(_volume))
        sound.play()
    except Exception as exc:
        _degrade(exc)


def play_explosion(radius):
    """Explosion pitched by the destroyed rock's size tier.

    The tier routing lives here so the sweep's call site stays one line —
    it already has the radius. Same size bands as points_for (hud.py).
    """
    if radius >= ASTEROID_MIN_RADIUS * 3:
        play(SFX_EXPLOSION_LARGE)
    elif radius >= ASTEROID_MIN_RADIUS * 2:
        play(SFX_EXPLOSION_MEDIUM)
    else:
        play(SFX_EXPLOSION_SMALL)


def _degrade(exc):
    """A play call failed: warn once, then silence for the rest of the run."""
    global _sounds
    if _sounds:
        print(
            f"[sound] warning: playback failed, going silent: {exc}",
            file=sys.stderr,
        )
        _sounds = {}


# --- ambient music loop (Tier 3) ----------------------------------------------


def music_gain(volume):
    """The loop's mixer gain at a master level: the SFX scale dropped by the
    bed's own MUSIC_GAIN so the music sits under every cue. Pure."""
    return master_gain(volume) * MUSIC_GAIN


def update_music(active):
    """The per-frame gameplay gate for the ambient loop (idempotent).

    True — a live run — keeps the loop audible; False (the menu, the
    game-over screen) stops it. A paused run is still live, so the bed
    keeps breathing under the overlay — M stays live there too. Mute and
    the master level reach the loop through the same setters as the SFX,
    so this call only has to carry the run/overlay boundary.
    """
    global _music_on
    _music_on = bool(active)
    _refresh_music()


def _refresh_music():
    """Reconcile the loop with the current wants: start it when gameplay
    wants audio and the mixer is not already looping it, stop it when it
    should be silent, and re-apply the gain so volume steps land live.
    Any mixer failure degrades like the SFX — one warning, then silence
    for the rest of the run."""
    global _music, _music_playing
    if _music is None:
        return
    try:
        if _music_on and not _muted:
            _music.set_volume(music_gain(_volume))
            if not _music_playing:
                _music.play(loops=-1)
                _music_playing = True
        elif _music_playing:
            _music.stop()
            _music_playing = False
    except Exception as exc:
        print(
            f"[sound] warning: music failed, going silent: {exc}",
            file=sys.stderr,
        )
        _music = None
        _music_playing = False


# --- synthesis ---------------------------------------------------------------


def _render(duration, wave):
    """Sample wave(t, progress) over the duration into float samples in [-1, 1]."""
    frames = int(SFX_SAMPLE_RATE * duration)
    return [max(-1.0, min(1.0, wave(i / SFX_SAMPLE_RATE, i / frames)))
            for i in range(frames)]


def _make_sound(samples):
    """Wrap float samples in a mixer-format Sound: interleaved stereo signed
    16-bit at the mixer's init rate — hand-rolled, no numpy."""
    buf = array.array("h")
    for value in samples:
        sample = int(value * 32767)
        buf.append(sample)
        buf.append(sample)  # left + right
    return pygame.mixer.Sound(buffer=buf)


def chirp(t, start_hz, end_hz, duration):
    """Linear frequency sweep start->end Hz; exact chirp phase integral."""
    mid = (start_hz + end_hz) / 2
    half = (end_hz - start_hz) / 2
    return math.sin(2 * math.pi * (mid * t + half * t * t / duration))


def build_shoot():
    """The 'pew': a descending chirp through a fast exponential decay."""
    start, end = SFX_SHOOT_SWEEP

    def wave(t, progress):
        return (
            chirp(t, start, end, SFX_SHOOT_DURATION)
            * math.exp(-6.0 * progress)
            * SFX_SHOOT_VOLUME
        )

    return _make_sound(_render(SFX_SHOOT_DURATION, wave))


def build_explosion(tier):
    """Noise burst over a low thump, from the tier table in constants.py.

    A fixed seed keeps the buffers deterministic — same sounds every run,
    same sounds in tests.
    """
    params = SFX_EXPLOSION_TIERS[tier]
    rng = random.Random(SFX_NOISE_SEED)

    def wave(t, progress):
        decay = math.exp(-4.0 * progress)
        noise = rng.uniform(-1.0, 1.0) * params["brightness"]
        thump = chirp(t, params["thump_hz"], params["thump_hz"] * 0.5,
                      params["duration"])
        return (noise + thump * (1.0 - progress)) * decay * SFX_EXPLOSION_VOLUME

    return _make_sound(_render(params["duration"], wave))


def build_powerup():
    """Rising chirp with a triangle attack/decay window — the pickup jingle."""
    start, end = SFX_POWERUP_SWEEP

    def wave(t, progress):
        window = min(progress / 0.2, (1.0 - progress) / 0.3, 1.0)
        return (
            chirp(t, start, end, SFX_POWERUP_DURATION)
            * max(0.0, window)
            * SFX_POWERUP_VOLUME
        )

    return _make_sound(_render(SFX_POWERUP_DURATION, wave))


def build_game_over():
    """A long descending tone: the run winding down."""
    start, end = SFX_GAME_OVER_SWEEP

    def wave(t, progress):
        return (
            chirp(t, start, end, SFX_GAME_OVER_DURATION)
            * (1.0 - progress)
            * SFX_GAME_OVER_VOLUME
        )

    return _make_sound(_render(SFX_GAME_OVER_DURATION, wave))


def build_dash():
    """A crisp whoosh: bright noise over a fast falling chirp, swelling
    and gone in under a fifth of a second (insanity core)."""
    start, end = SFX_DASH_SWEEP
    rng = random.Random(SFX_NOISE_SEED)  # deterministic, like the explosions

    def wave(t, progress):
        window = min(progress / 0.25, (1.0 - progress) / 0.4, 1.0)
        noise = rng.uniform(-1.0, 1.0) * SFX_DASH_BRIGHTNESS
        air = chirp(t, start, end, SFX_DASH_DURATION) * 0.5
        return (noise + air) * max(0.0, window) * SFX_DASH_VOLUME

    return _make_sound(_render(SFX_DASH_DURATION, wave))


def build_combo_break():
    """A descending sigh: the chain dying audibly (insanity core)."""
    start, end = SFX_COMBO_BREAK_SWEEP

    def wave(t, progress):
        window = min(progress / 0.15, (1.0 - progress) / 0.5, 1.0)
        return (
            chirp(t, start, end, SFX_COMBO_BREAK_DURATION)
            * max(0.0, window)
            * SFX_COMBO_BREAK_VOLUME
        )

    return _make_sound(_render(SFX_COMBO_BREAK_DURATION, wave))


def build_saucer():
    """A two-tone warble (insanity threats): two detuned tones beating
    against each other while the shot leaves — the UFO voice."""
    tone_a, tone_b = SFX_SAUCER_TONES

    def wave(t, progress):
        window = min(progress / 0.2, (1.0 - progress) / 0.3, 1.0)
        beat = (
            chirp(t, tone_a, tone_a, SFX_SAUCER_DURATION) * 0.5
            + chirp(t, tone_b, tone_b, SFX_SAUCER_DURATION) * 0.5
        )
        return beat * max(0.0, window) * SFX_SAUCER_VOLUME

    return _make_sound(_render(SFX_SAUCER_DURATION, wave))


def build_boss():
    """A low double-thump (insanity threats): the field's weight arriving —
    two 90 Hz thumps, the second a fourth lower and heavier."""

    def wave(t, progress):
        # Each half of the buffer is one thump: a fast-decaying downward
        # sweep, the second a fourth lower and heavier.
        half = 0.5
        if progress < half:
            local = progress / half
            hz = SFX_BOSS_THUMP_HZ
            weight = 0.8
        else:
            local = (progress - half) / half
            hz = SFX_BOSS_THUMP_HZ * 2 / 3  # a fourth down
            weight = 1.0
        thump = chirp(local * SFX_BOSS_DURATION / 2, hz, hz * 0.5,
                      SFX_BOSS_DURATION / 2)
        return thump * math.exp(-5.0 * local) * weight * SFX_BOSS_VOLUME

    return _make_sound(_render(SFX_BOSS_DURATION, wave))


def build_blackhole():
    """A low rumble (insanity threats): dull noise over a sinking tone,
    swelling slowly — the well breathing open."""
    start, end = SFX_BLACKHOLE_SWEEP
    rng = random.Random(SFX_NOISE_SEED)  # deterministic, like the explosions

    def wave(t, progress):
        window = min(progress / 0.4, (1.0 - progress) / 0.4, 1.0)
        noise = rng.uniform(-1.0, 1.0) * SFX_BLACKHOLE_BRIGHTNESS
        tone = chirp(t, start, end, SFX_BLACKHOLE_DURATION) * 0.7
        return (noise + tone) * max(0.0, window) * SFX_BLACKHOLE_VOLUME

    return _make_sound(_render(SFX_BLACKHOLE_DURATION, wave))


def build_curse():
    """A dissonant sting (insanity chaos): two tones a rubbed half-step
    apart, sinking together — the sound that makes the next ? hesitate."""
    tone_a, tone_b = SFX_CURSE_TONES

    def wave(t, progress):
        window = min(progress / 0.1, (1.0 - progress) / 0.6, 1.0)
        # Both tones sink ~15% together — a falling pair that never
        # resolves, the beat widening as it dies.
        slide = 1.0 - 0.15 * progress
        sting = (
            chirp(t, tone_a * slide, tone_a * slide * 0.85, SFX_CURSE_DURATION) * 0.5
            + chirp(t, tone_b * slide, tone_b * slide * 0.85, SFX_CURSE_DURATION) * 0.5
        )
        return sting * max(0.0, window) * SFX_CURSE_VOLUME

    return _make_sound(_render(SFX_CURSE_DURATION, wave))
def denied_thud_gain(t, thud_s, gap_s):
    """The buzz's on/off gate: 1.0 inside a thud, 0.0 in the gap between
    them — pure so the two-thud shape is pinnable in tests."""
    cycle = t % (thud_s + gap_s)
    return 1.0 if cycle < thud_s else 0.0


def build_denied():
    """Two low square thuds with a gap — the can't-afford-it buzz.

    A square carrier (the sign of a sine) reads as a buzz where a chirp
    would read as a tone; the whole-cue decay leans the second thud softer
    than the first, like a door thudded twice.
    """
    span = 2 * SFX_DENIED_THUD_S + SFX_DENIED_GAP_S

    def wave(t, progress):
        thud = math.copysign(1.0, math.sin(2 * math.pi * SFX_DENIED_HZ * t))
        return (
            thud
            * denied_thud_gain(t, SFX_DENIED_THUD_S, SFX_DENIED_GAP_S)
            * math.exp(-3.0 * progress)
            * SFX_DENIED_VOLUME
        )

    return _make_sound(_render(span, wave))


def wave_clear_note(t, note_s, arpeggio):
    """The jingle's oscillator: one humped sine per arpeggio slot — pure.

    The carrier restarts at each slot boundary (local phase), so the note
    attacks clean instead of clicking mid-phase; the sine hump is the
    attack/decay envelope. Beyond the last slot the final note holds.
    """
    index = min(int(t / note_s), len(arpeggio) - 1)
    local = t - index * note_s
    hump = math.sin(math.pi * (local / note_s))
    return math.sin(2 * math.pi * arpeggio[index] * local) * hump


def build_wave_clear():
    """A rising major arpeggio — the field is clear, the wave is won."""
    notes = len(SFX_WAVE_CLEAR_ARPEGGIO)

    def wave(t, progress):
        return (
            wave_clear_note(t, SFX_WAVE_CLEAR_NOTE_S, SFX_WAVE_CLEAR_ARPEGGIO)
            * SFX_WAVE_CLEAR_VOLUME
        )

    return _make_sound(_render(notes * SFX_WAVE_CLEAR_NOTE_S, wave))


def build_drone_fire():
    """The turret pew: the player's shot shape, shorter and brighter."""
    start, end = SFX_DRONE_FIRE_SWEEP

    def wave(t, progress):
        return (
            chirp(t, start, end, SFX_DRONE_FIRE_DURATION)
            * math.exp(-6.0 * progress)
            * SFX_DRONE_FIRE_VOLUME
        )

    return _make_sound(_render(SFX_DRONE_FIRE_DURATION, wave))


def build_ambient_loop():
    """The gameplay bed: a slow bass heartbeat under sparse, detuned pads.

    Seamless by construction — every frequency below is an integer multiple
    of the loop fundamental (1 / MUSIC_LOOP_SECONDS) and every envelope is
    periodic over the same span, so the wrap lands on identical phase and
    looping never clicks. Deterministic like the cue builders: pure math.
    """

    def wave(t, progress):
        # The heartbeat: one exp-decaying pulse per beat over an A1 sine.
        beat = math.exp(-3.5 * (t % MUSIC_BASS_BEAT_S) / MUSIC_BASS_BEAT_S)
        bass = (
            math.sin(2 * math.pi * MUSIC_BASS_HZ * t) * beat * MUSIC_BASS_VOLUME
        )
        # The pads trade places once per loop — (1 - cos) / 2 swells 0→1→0
        # and its mirror does the opposite — so the bed breathes rather
        # than drones: the detuned A2 pair swells in while the fifth (E3)
        # swells out.
        swell = (1.0 - math.cos(2 * math.pi * progress)) / 2
        pad_root = (
            math.sin(2 * math.pi * MUSIC_PAD_A_HZ * t)
            + math.sin(2 * math.pi * MUSIC_PAD_A_DETUNE_HZ * t)
        ) / 2
        pad_fifth = math.sin(2 * math.pi * MUSIC_PAD_B_HZ * t)
        pads = (pad_root * swell + pad_fifth * (1.0 - swell)) * MUSIC_PAD_VOLUME
        return bass + pads

    return _make_sound(_render(MUSIC_LOOP_SECONDS, wave))

