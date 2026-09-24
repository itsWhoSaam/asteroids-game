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
)
from hud import SAVE_PATH, ComboMeter, Score, combo_multiplier
from logger import log_event
import sound
from particles import burst


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
        # Insanity core: the shot-kill chain. Score-only — register_kill is
        # the ONLY route into it, so clicks and nukes stay combo-free.
        self.combo = ComboMeter()

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

    @property
    def new_high(self):
        """True once this run has beaten the persisted high score."""
        return self._score.beaten

    def add_score(self, points):
        """Points for a destroyed asteroid, through the F1 seam."""
        self._score.add_score(points)

    def register_kill(self, points):
        """A rock destroyed by player-or-drone fire: advance the chain and
        pay points × the chain multiplier through the F1 seam.

        Combo is a score feature, not a currency feature (locked decision):
        the destruction diff's credit mint never sees the multiplier. Chip
        clicks and nukes never route here — they pay credits through the
        diff, combo-free, exactly as they did before this build."""
        mult = combo_multiplier(self.combo.register_kill())
        self.add_score(round(points * mult))

    def break_combo(self):
        """Drop the live chain — the price of a life lost or a dash."""
        self.combo.break_chain()

    def tick(self, dt):
        """Run-state frame tick: the combo window drains on the same dt the
        simulation runs on, so a hit-stop freeze holds the chain alive too."""
        self.combo.tick(dt)

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
        if self.particles is not None:
            burst(self.player.position, self.player.radius,
                  PLAYER_DEATH_BURST_INTENSITY)
        if self.shake is not None:
            self.shake.kick(SHAKE_PLAYER_DEATH)
        self.lives -= 1
        # A life lost breaks the chain — the multiplier dies with the ship.
        # An absorbed (shielded) hit returned above and keeps its chain.
        self.break_combo()
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
        log_event("game_over", score=self.score, high_score=self.high_score)
        sound.play(sound.SFX_GAME_OVER)  # F6: the run winding down

    def restart(self):
        """Full reset: counters to wave-1 start AND world cleared."""
        self._score.reset()
        self.lives = PLAYER_START_LIVES
        self.wave = 1
        self.state = "playing"
        # Insanity core: the combo meter and its run stats die with the run.
        self.combo.reset()
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
