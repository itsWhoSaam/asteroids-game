import pygame

from constants import (
    CLICK_DAMAGE_BASE,
    FLOAT_COLOR,
    FLOAT_FONT_SIZE,
    FLOAT_LIFETIME_SECONDS,
    FLOAT_RISE_SPEED,
    HUD_LINE_STEP,
    HUD_MARGIN,
    IDLE_AUTOSAVE_SECONDS,
    SHOP_BRIGHT_COLOR,
    MAX_DT, SCREEN_WIDTH, SCREEN_HEIGHT,
)
from asteroid import Asteroid
from asteroidfield import AsteroidField
from economy import Economy
from game import Game
from hud import draw_hud, draw_game_over, hud_font, points_for
from logger import log_state, log_event
from player import Player
from shop import Shop
from shot import Shot


def compute_dt(ms):
    """Clamped frame delta: a stall (alt-tab, window drag) must never move
    entities far enough to skip over a collision unchecked."""
    return min(ms / 1000, MAX_DT)


def handle_collisions(asteroids, shots, player1, game):
    # The sweep reports hits to the Game instead of exiting the process
    # (engagement F2): a hit costs one of the lives, the ship respawns
    # invulnerable, and the run ends only at zero lives. Invulnerability is
    # checked before any hit is resolved, so a respawning ship can sit on
    # an asteroid for the grace window without losing another life.
    for asteroid in asteroids:
        if not asteroid.alive():
            continue
        if (
            game.state == "playing"
            and not player1.invulnerable
            and asteroid.collides_with(player1)
        ):
            log_event("player_hit")
            game.player_hit()
        for shot in shots:
            if not shot.alive():
                continue
            if asteroid.collides_with(shot):
                log_event("asteroid_shot")
                asteroid.split()
                shot.kill()
                game.add_score(points_for(asteroid.radius))
                break  # the hit killed the asteroid; skip its remaining shots


class _ClickPoint:
    """Zero-radius cursor probe so asteroid.collides_with works unchanged."""

    def __init__(self, pos):
        self.position = pygame.Vector2(pos)
        self.radius = 0.0


def asteroid_at(asteroids, pos):
    """The asteroid under the cursor, or None.

    Reuses the CircleShape collision test through a zero-radius probe; when
    several rocks overlap, the one nearest the click wins.
    """
    probe = _ClickPoint(pos)
    best = None
    best_dist = float("inf")
    for asteroid in asteroids:
        if not asteroid.collides_with(probe):
            continue
        dist = asteroid.position.distance_to(probe.position)
        if dist < best_dist:
            best, best_dist = asteroid, dist
    return best


def destroyed_asteroids(previous, current):
    """Asteroids that were on screen last frame and are gone now.

    The frame-to-frame group diff is the destruction detector: shots kill
    inside handle_collisions and clicks inside take_chip, but both funnel
    through kill() → group removal, so one poll sees every source without
    touching handle_collisions' pinned signature. split() children are new
    sprites absent from `previous`, so a split pays for the parent only.
    Asteroids flagged despawned (drifted off-screen, or the field cleared
    for a restart) are culls, not kills — they never mint.
    """
    return [
        asteroid
        for asteroid in previous
        if asteroid not in current and not asteroid.despawned
    ]


_float_font_cache = None


def float_font():
    """Lazily built small font for floating credit numbers."""
    global _float_font_cache
    if _float_font_cache is None:
        _float_font_cache = pygame.font.Font(None, FLOAT_FONT_SIZE)
    return _float_font_cache


def float_label(amount):
    """The '+N' string over a wreck; credits render as whole numbers."""
    return f"+{int(amount)}"


def click_damage(shop):
    """Chip damage per click: the constant base scaled by Nanoblade levels."""
    return CLICK_DAMAGE_BASE * shop.click_damage_mult()


class FloatingText(pygame.sprite.Sprite):
    """A '+N' credit number rising from a fresh wreck (idle core).

    Lifetime runs on the dt-timer pattern — no wall-clock calls, so
    headless runs and tests step it deterministically.
    """

    containers = ()

    def __init__(self, x, y, amount, label=None, color=FLOAT_COLOR):
        if self.containers:
            super().__init__(self.containers)
        else:
            super().__init__()
        self.position = pygame.Vector2(x, y)
        self.surface = float_font().render(label or float_label(amount), True, color)
        self.lifetime = FLOAT_LIFETIME_SECONDS

    def update(self, dt):
        self.lifetime -= dt
        self.position.y -= FLOAT_RISE_SPEED * dt
        if self.lifetime <= 0:
            self.kill()

    def draw(self, screen):
        screen.blit(self.surface, self.surface.get_rect(center=self.position))


def draw_credits(screen, credits):
    """Idle ledger readout under the score HUD — the economy's visible half."""
    surface = hud_font().render(f"Credits: {int(credits)}", True, FLOAT_COLOR)
    screen.blit(surface, (HUD_MARGIN, HUD_MARGIN + 3 * HUD_LINE_STEP))


def main():
    pygame.init()
    game_clk = pygame.time.Clock()
    dt = 0
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    updatable = pygame.sprite.Group()
    drawable = pygame.sprite.Group()
    asteroids = pygame.sprite.Group()
    shots = pygame.sprite.Group()
    floaters = pygame.sprite.Group()

    Asteroid.containers = (asteroids, updatable, drawable)
    Shot.containers = (shots, updatable, drawable)
    AsteroidField.containers = updatable
    FloatingText.containers = (floaters, updatable, drawable)
    asteroid_field = AsteroidField()

    Player.containers = (updatable, drawable)
    player1 = Player(SCREEN_WIDTH/2, SCREEN_HEIGHT/2 )
    game = Game(player1, asteroids, shots)
    economy = Economy()
    shop = Shop(economy, player1)  # applies any save-loaded effect levels

    prev_asteroids = set(asteroids)
    autosave_timer = 0.0

    while True:
        log_state()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                economy.save()
                pygame.quit()
                return
            if event.type == pygame.KEYDOWN and game.state == "game_over":
                # R restarts, Q quits (engagement F2). Kept in this event-pump
                # block; later features add their input alongside it.
                if event.key == pygame.K_r:
                    # A cleared field is not player destruction: flag every
                    # rock as a cull so the diff poll never mints for restart.
                    for asteroid in asteroids:
                        asteroid.despawned = True
                    game.restart()
                elif event.key == pygame.K_q:
                    economy.save()
                    pygame.quit()
                    return
            if event.type == pygame.KEYDOWN:
                # Shop keys 1–4 (idle shop): additive beside F2's R/Q —
                # different keys, so neither branch shadows the other.
                purchase = shop.handle_key(event.key)
                if purchase is not None:
                    x, y = shop.cell_center(purchase.name)
                    FloatingText(
                        x,
                        y,
                        0,
                        label=f"{purchase.title} Lv {purchase.level}",
                        color=SHOP_BRIGHT_COLOR,
                    )
            if event.type == pygame.MOUSEBUTTONDOWN:
                # Idle core: a click chips the rock under the cursor. take_chip
                # routes any kill through split(), so every destruction source
                # shares one downstream mint path (the group diff below).
                target = asteroid_at(asteroids, event.pos)
                if target is not None:
                    target.take_chip(click_damage(shop))

        ms = game_clk.tick(60)
        dt = compute_dt(ms)
        updatable.update(dt)
        # player1.update(dt)

        handle_collisions(asteroids, shots, player1, game)

        # Destruction → credits: diff this frame's field against the last,
        # mint once per wreck, float a '+N' over the wreck.
        for wreck in destroyed_asteroids(prev_asteroids, asteroids):
            payout = economy.mint(wreck.radius)
            log_event("credit_minted", amount=payout)
            FloatingText(wreck.position.x, wreck.position.y, payout)
        prev_asteroids = set(asteroids)

        autosave_timer += dt
        if autosave_timer >= IDLE_AUTOSAVE_SECONDS:
            autosave_timer = 0.0
            economy.save()

        screen.fill("black")

        for each in drawable:
            each.draw(screen)
        # player1.draw(screen)

        draw_hud(screen, game.score, lives=game.lives)
        draw_credits(screen, economy.credits)
        shop.draw_panel(screen)
        if game.state == "game_over":
            draw_game_over(screen, game.score, new_high=game.new_high)

        pygame.display.flip()
        


if __name__ == "__main__":
    main()
