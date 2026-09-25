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
    SFX_CHANNELS,
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
    SFX_SHOOT,
    SFX_SHOOT_DURATION,
    SFX_SHOOT_SWEEP,
    SFX_SHOOT_VOLUME,
    VOLUME_DEFAULT,
    VOLUME_MAX,
    VOLUME_MIN,
)

# The synthesized SFX table, filled once by init(): name -> mixer.Sound.
# Empty means "audio unavailable" — every play call no-ops.
_sounds = {}
_muted = False
_volume = VOLUME_DEFAULT  # master level 0–100; playback scales by it


def init():
    """Bring the mixer up and synthesize the SFX table once.

    Any failure leaves the module a silent no-op: the game runs and plays
    nothing. The failure surfaces once as a warning instead of being
    swallowed silently or crashing the run.
    """
    global _sounds
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
        }
    except Exception as exc:
        _sounds = {}
        print(
            f"[sound] warning: mixer unavailable, running silent: {exc}",
            file=sys.stderr,
        )


def set_muted(muted):
    """Playback suppression switch — the game keeps simulating either way."""
    global _muted
    _muted = bool(muted)


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
