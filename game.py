"""Run-state owner: lives, respawn, game over, restart (engagement F2).

The single owner of run state. The collision sweep in main.handle_collisions
reports hits here instead of killing the process, so death is a setback with
a comeback, not an exit code. The F1 Score seam is absorbed wholesale:
add_score delegates to it, keeping high-score persistence, the
high_score_beaten event, and the save loader's read-modify-write contract
(unknown keys ride along) untouched.
"""

from constants import (
    PLAYER_DEATH_BURST_INTENSITY,
    PLAYER_START_LIVES,
    SHAKE_PLAYER_DEATH,
    VOLUME_STEP,
)
from comicfx import BURST_WORD_DEATH, spawn_burst
from hud import SAVE_PATH, Score
from logger import log_event
import sound
from particles import burst
from stats import RunStats


class Game:
    """Run state plus the world refs a full reset needs.

    The player and sprite groups are injected so respawn/restart can reset
    the whole world, not just the counters — a stale asteroid surviving into
    a fresh run would be a visible lie.
    """

    def __init__(self, player, asteroids, shots, powerups=None, save_path=SAVE_PATH,
                 particles=None, shake=None):
        self.player = player
        self.asteroids = asteroids
        self.shots = shots
        # The pickups group (F4) so restart can clear the whole world; the
        # None default keeps every pre-F4 constructor call working unchanged.
        self.powerups = powerups
        # F5 effect sinks: the death burst and shake fire from the one place
        # a life is actually lost. None keeps every pre-F5 call unchanged.
        self.particles = particles
        self.shake = shake
        self._score = Score(save_path)
        self.lives = PLAYER_START_LIVES
        self.wave = 1
        self.state = "playing"  # "playing" | "game_over"
        # Tier 1 pause: True while P/Esc has frozen a live run. Never
        # persisted, and only ever set inside "playing" — see toggle_pause.
        self.paused = False
        # Tier 1 help: True while the keybind list is up over dimmed play.
        # UI state like pause — never persisted, toggled only in "playing"
        # (see toggle_help), and cleared by game over and restart so a stale
        # list never covers another screen's prompt.
        self.help_open = False
        # Run-stat counters (run-stats PR): per-run, never saved. The player
        # records against the run's one instance — injected here, the one
        # place both exist — so restart() must reset it in place, never
        # rebind it, or the ship would keep scoring into a dead run's counters.
        self.stats = RunStats()
        self.player.stats = self.stats

    @property
    def score(self):
        return self._score.current

    @property
    def high_score(self):
        return self._score.high

    @property
    def muted(self):
        return self._score.muted

    def toggle_mute(self):
        """Flip and persist the mute preference (F6); returns the new state.

        Playback-only: the sim never stops for audio, so this is not run
        state — main() relays the return value to the sound module."""
        return self._score.set_muted(not self.muted)

    def toggle_pause(self):
        """Flip the pause flag on a live run only; True when it flipped.

        Game over owns its own screen (R/Q there, no pause overlay), and a
        flag riding into a fresh run would freeze wave 1 — so the gate
        refuses outside "playing", and restart()/game_over() clear it."""
        if self.state != "playing":
            return False
        self.paused = not self.paused
        log_event("paused" if self.paused else "resumed")
        return True

    def toggle_help(self):
        """Flip the help overlay on a live run only; True when it flipped.

        Same gate as toggle_pause: the game-over screen owns its R/Q prompt
        and a fresh run starts clean — restart()/game_over() clear the flag.
        Unlike pause, help freezes nothing (the run continues under the
        dimmed list), so this touches no simulation state and logs no run
        event — the list is documentation, not a world change."""
        if self.state != "playing":
            return False
        self.help_open = not self.help_open
        return True

    @property
    def volume(self):
        """The persisted master level, 0–100 (UX wave)."""
        return self._score.volume

    def step_volume(self, direction):
        """Step the master level by one VOLUME_STEP toward `direction`
        (+1 / -1), clamped to 0–100 and persisted through the save loader;
        returns the new level for main() to relay to the sound module.

        Playback-only like mute — not run state, so restart hooks don't
        touch it. Mute never routes through here: stepping keeps the level
        exactly as it was left.
        """
        return self._score.set_volume(
            sound.clamp_volume(self.volume + direction * VOLUME_STEP)
        )

    @property
    def new_high(self):
        """True once this run has beaten the persisted high score."""
        return self._score.beaten

    def add_score(self, points):
        """Points for a destroyed asteroid, through the F1 seam."""
        self._score.add_score(points)

    def player_hit(self):
        """A live (playing) collision reached the ship: a stocked shield eats
        it first — the charge is spent, no life lost, no respawn (F4) —
        otherwise it costs one of the lives."""
        if self.state != "playing":
            return
        if self.player.absorb_hit():
            return
        # F5: a life lost looks like one — debris at the hull and a strong
        # shake — whether this hit respawns the ship or ends the run. An
        # absorbed (shielded) hit is neither, so it stays silent. The burst
        # is at the death site: respawn() moves the ship right after.
        # V4: the death word pops first, so it joins fx ahead of the debris
        # cloud and reads behind it — ZAP!, the player's burst.
        spawn_burst(self.player.position, self.player.radius, BURST_WORD_DEATH)
        if self.particles is not None:
            burst(self.player.position, self.player.radius,
                  PLAYER_DEATH_BURST_INTENSITY)
        if self.shake is not None:
            self.shake.kick(SHAKE_PLAYER_DEATH)
        self.lives -= 1
        if self.lives <= 0:
            self.lives = 0
            self.game_over()
        else:
            self.respawn()

    def respawn(self):
        """Center the ship, zero its velocity, grant the grace window."""
        self.player.respawn()

    def game_over(self):
        """Run ends: flip state; final score vs high score is on the overlay."""
        self.state = "game_over"
        # Frozen worlds resolve no hits, so a pause can't coexist with game
        # over — clearing keeps that invariant structural: the game-over
        # screen is never dimmed by a stale pause flag. A stale help list
        # would cover the R/Q prompt the same way, so it closes here too.
        self.paused = False
        self.help_open = False
        log_event("game_over", score=self.score, high_score=self.high_score)
        sound.play(sound.SFX_GAME_OVER)  # F6: the run winding down

    def restart(self):
        """Full reset: counters to wave-1 start AND world cleared."""
        self._score.reset()
        # Run stats (run-stats PR): run-scoped counters die with the run,
        # zeroed in place — both restart hooks land here, and the player
        # holds this very instance.
        self.stats.reset()
        self.lives = PLAYER_START_LIVES
        self.wave = 1
        self.state = "playing"
        # Both restart hooks land here (game-over R and the pause overlay's
        # R): a fresh run is always live, unpaused, and help-free.
        self.paused = False
        self.help_open = False
        # kill() detaches each sprite from ALL its groups (asteroids are also
        # in updatable/drawable) — emptying one group would leave zombie rocks
        # drifting and rendering, unshootable.
        for asteroid in list(self.asteroids):
            asteroid.kill()
        for shot in list(self.shots):
            shot.kill()
        if self.powerups is not None:
            # Pickups are world objects too: a stale SHIELD surviving into a
            # fresh run would be the same visible lie as a stale rock (F4).
            for powerup in list(self.powerups):
                powerup.kill()
        self.player.clear_powerups()
        self.player.respawn()
        log_event("restart")
