"""Run-state owner: lives, respawn, game over, restart (engagement F2).

The single owner of run state. The collision sweep in main.handle_collisions
reports hits here instead of killing the process, so death is a setback with
a comeback, not an exit code. The F1 Score seam is absorbed wholesale:
add_score delegates to it, keeping high-score persistence, the
high_score_beaten event, and the save loader's read-modify-write contract
(unknown keys ride along) untouched.
"""

from challenge import daily_slug, load_daily_best, record_daily_score
from constants import (
    DIFFICULTY_TABLE,
    PLAYER_DEATH_BURST_INTENSITY,
    SHAKE_PLAYER_DEATH,
    VOLUME_STEP,
)
from comicfx import BURST_WORD_DEATH, spawn_burst
from hud import SAVE_PATH, ComboMeter, Score, combo_multiplier
from logger import log_event
import sound
from particles import burst
from stats import RunStats


def mode_lives(mode):
    """Starting lives for a difficulty mode (Tier 2), pure for the table
    tests: Easy 5, Normal the shipped 3, Hard 2."""
    return DIFFICULTY_TABLE[mode]["lives"]


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
        # The daily challenge records through the same file (Tier 3) — kept
        # here so the game-over write lands where this Game's Score and the
        # Economy ledger read, not some other process's repo-root save.
        self.save_path = save_path
        # Tier 2 difficulty modes: the mode persists across runs (the save
        # merge carries it), so a fresh Game resumes the saved choice and
        # starts on its lives row. Lives apply at start and at restart().
        self.lives = mode_lives(self._score.mode)
        self.wave = 1
        # "playing" | "game_over" | "menu" — "menu" is main()'s boot state
        # (the difficulty select); every run gate here checks != "playing",
        # so a menu frame freezes the run for free.
        self.state = "playing"
        # Insanity core: the shot-kill chain. Score-only — register_kill is
        # the ONLY route into it, so clicks and nukes stay combo-free.
        self.combo = ComboMeter()
        # Tier 1 pause: True while P/Esc has frozen a live run. Never
        # persisted, and only ever set inside "playing" — see toggle_pause.
        self.paused = False
        # Tier 1 help: True while the keybind list is up over dimmed play.
        # UI state like pause — never persisted, toggled only in "playing"
        # (see toggle_help), and cleared by game over and restart so a stale
        # list never covers another screen's prompt.
        self.help_open = False
        # Near-miss graze bonus (Tier 3): a sim-time run clock for the
        # per-pair cooldowns plus the cooldown table itself, keyed on the
        # live rocks — this one ship is each pair's other half. The clock
        # only ever advances (tick), so restarting needs no reset of it;
        # the cooldowns clear with the world they key on (restart).
        self.now = 0.0
        self.graze_cooldowns = {}
        # Run-stat counters (run-stats PR): per-run, never saved. The player
        # records against the run's one instance — injected here, the one
        # place both exist — so restart() must reset it in place, never
        # rebind it, or the ship would keep scoring into a dead run's counters.
        self.stats = RunStats()
        self.player.stats = self.stats
        # Daily seeded challenge (Tier 3): the daily flag is selection
        # state like the difficulty mode — toggled on the start/game-over
        # flow, it lands at launch (restart_run stamps the challenge date
        # and seeds the field). Session state, deliberately not persisted:
        # a boot starts on the normal game. The day's best is cached here
        # because the boot menu reads it every frame — one save read at
        # construction, refreshed when a daily run records (game_over).
        self.daily = False
        self.daily_day = None
        self._daily_best = load_daily_best(path=save_path)

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

    @property
    def mode(self):
        """The selected difficulty (Tier 2), persisted via the Score seam."""
        return self._score.mode

    @property
    def high_scores(self):
        """Every mode's persisted best — the difficulty menu reads it."""
        return self._score.mode_highs

    def set_mode(self, mode):
        """Select the difficulty for the NEXT run (start/game-over flow).

        Persists through the Score seam, which retargets the high-score
        comparison to the new mode's best. Lives apply at restart(), not
        here — selection never lands mid-run, so both restart hooks and the
        menu's launch land the mode's lives the same way.
        """
        self._score.set_mode(mode)
        log_event("difficulty_selected", mode=mode)
        return self._score.mode

    def toggle_daily(self):
        """Flip the daily-challenge selection on the start/game-over flow
        (Tier 3); True when it flipped.

        The gate mirrors set_mode's: D means nothing mid-run — a live run
        cannot become daily halfway through its seed, and 1/2/3 already
        mean the shop keys there. The flag survives restart() like the
        mode does (selection, not counters), so the game-over R replays
        today's seeded run; D off on the game-over screen re-arms normal.
        """
        if self.state not in ("menu", "game_over"):
            return False
        self.daily = not self.daily
        log_event("daily_toggled", on=self.daily)
        return True

    @property
    def daily_best(self):
        """The day's persisted best (daily challenge), as cached at boot
        or the last recorded game over — the menu row's readout."""
        return self._daily_best

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
        simulation runs on, so a hit-stop freeze holds the chain alive too.
        The run clock rides the same dt — graze cooldowns read it, so a
        frozen frame holds them with everything else."""
        self.now += dt
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
        # V4: the death word pops first, so it joins fx ahead of the debris
        # cloud and reads behind it — ZAP!, the player's burst.
        spawn_burst(self.player.position, self.player.radius, BURST_WORD_DEATH)
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
        # Frozen worlds resolve no hits, so a pause can't coexist with game
        # over — clearing keeps that invariant structural: the game-over
        # screen is never dimmed by a stale pause flag. A stale help list
        # would cover the R/Q prompt the same way, so it closes here too.
        self.paused = False
        self.help_open = False
        # Daily seeded challenge (Tier 3): a finished daily run offers its
        # score to the challenge date's best — the run's own date (stamped
        # at launch), so a run spanning midnight records against the day it
        # was seeded for. The merge write touches only the daily_best key.
        if self.daily and self.daily_day is not None:
            if record_daily_score(self.daily_day, self._score.current,
                                  path=self.save_path):
                self._daily_best = self._score.current
                log_event(
                    "daily_best",
                    date=daily_slug(self.daily_day),
                    score=self._score.current,
                )
        log_event("game_over", score=self.score, high_score=self.high_score)
        sound.play(sound.SFX_GAME_OVER)  # F6: the run winding down

    def restart(self):
        """Full reset: counters to wave-1 start AND world cleared."""
        self._score.reset()
        # Run stats (run-stats PR): run-scoped counters die with the run,
        # zeroed in place — both restart hooks land here, and the player
        # holds this very instance.
        self.stats.reset()
        self.lives = mode_lives(self.mode)
        self.wave = 1
        self.state = "playing"
        # Insanity core: the combo meter and its run stats die with the run.
        self.combo.reset()
        # Graze cooldowns (Tier 3) key on the live rocks — cleared with the
        # world they key on. Both restart hooks land here (game-over R and
        # the pause overlay's R through restart_run), so a fresh run can
        # graze from its first frame.
        self.graze_cooldowns = {}
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
