"""The upgrade shop: definitions, purchase keys, effects, bottom panel.

Four upgrades bought with credits through the Economy ledger — upgrade_cost
and buy are its seams, never reimplemented here. Effects apply through the
hooks each module already exposes: the mouse branch multiplies
CLICK_DAMAGE_BASE by click_damage_mult(), the ship reads its cooldown_mult
attribute, and every mint() scales through Economy.income_multiplier().
Drones spawns one turret per level through drones.DroneBay.
"""

from dataclasses import dataclass

import pygame

import sound

from constants import (
    NANOBLADE_MULT_PER_LEVEL,
    FIRE_RATE_MULT_PER_LEVEL,
    INCOME_MULT_PER_LEVEL,
    POWERUPS,
    POWERUP_ACTIVE_COLOR,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHOP_BRIGHT_COLOR,
    SHOP_CELL_PADDING,
    SHOP_DIM_COLOR,
    SHOP_FONT_SIZE,
    SHOP_LINE_STEP,
    SHOP_PANEL_BG,
    SHOP_PANEL_BORDER,
    SHOP_PANEL_HEIGHT,
)


@dataclass(frozen=True)
class UpgradeDef:
    """One purchasable upgrade: identity, key binding, and effect copy.

    Balance lives in constants.UPGRADE_COSTS under the same name — the
    Economy reads it for the curve, so the numbers have exactly one home.
    """

    name: str
    title: str
    key: int  # pygame.K_1 … K_4 — the KEYDOWN code that buys it
    effect: str  # panel descriptor of what each level buys

    @property
    def key_label(self):
        """The digit the player presses (pygame digit keys are ASCII)."""
        return chr(self.key)


@dataclass(frozen=True)
class Purchase:
    """A completed buy — everything a confirmation float needs."""

    name: str
    title: str
    level: int
    cost: float


UPGRADES = (
    UpgradeDef("nanoblade", "Nanoblade", pygame.K_1, "click damage ×1.8/lvl"),
    UpgradeDef("fire_rate", "Fire-rate", pygame.K_2, "shot cooldown ×0.88/lvl"),
    UpgradeDef("income", "Income", pygame.K_3, "credit payouts ×1.15/lvl"),
    UpgradeDef("drone", "Drones", pygame.K_4, "auto-turret per level"),
)

_BY_KEY = {defn.key: defn for defn in UPGRADES}
_BY_NAME = {defn.name: defn for defn in UPGRADES}
_CELL_INDEX = {defn.name: index for index, defn in enumerate(UPGRADES)}

# Bought powerups (insane-powerups): key bindings read straight out of
# the POWERUPS table — the same table-driven shape as the upgrade defs
# and the sibling F4 drop tables, never redefined here.
_BY_POWERUP_KEY = {defn["key"]: name for name, defn in POWERUPS.items()}


def powerup_name_for_key(key):
    """The bought powerup bound to ``key`` (K_7/K_8/K_9/K_0), or None."""
    return _BY_POWERUP_KEY.get(key)


def cell_width():
    """Each upgrade owns an equal slice of the panel's width."""
    return SCREEN_WIDTH / len(UPGRADES)


def affordability_color(affordable):
    """Affordable cells glow; the rest sit dim until the ledger catches up."""
    return SHOP_BRIGHT_COLOR if affordable else SHOP_DIM_COLOR


_shop_font_cache = None


def shop_font():
    """Lazily built panel font; pygame.font is ready once pygame.init() ran."""
    global _shop_font_cache
    if _shop_font_cache is None:
        _shop_font_cache = pygame.font.Font(None, SHOP_FONT_SIZE)
    return _shop_font_cache


class Shop:
    """Purchase handling, effect application, and panel rendering."""

    def __init__(self, economy, player):
        self.economy = economy
        self.player = player
        # A loaded save may already carry Fire-rate levels: the ship must
        # start on its purchased cooldown, not the stock one.
        self.apply_effects()

    # --- effects ----------------------------------------------------------

    def apply_effects(self):
        """Push every player-attribute effect to its current level.

        Called at boot and after every purchase. The Income upgrade needs
        no push — mint() reads income_multiplier() live each payout.
        """
        self.player.cooldown_mult = self.cooldown_mult()

    def click_damage_mult(self):
        """Nanoblade's chip-damage multiplier at the current level."""
        return NANOBLADE_MULT_PER_LEVEL ** self.economy.levels["nanoblade"]

    def cooldown_mult(self):
        """Fire-rate's cooldown multiplier at the current level."""
        return FIRE_RATE_MULT_PER_LEVEL ** self.economy.levels["fire_rate"]

    # --- buying -----------------------------------------------------------

    def handle_key(self, key):
        """Buy the upgrade bound to ``key``; the Purchase, or None.

        None covers both "not a shop key" (F2's R/Q and the movement keys
        fall through untouched) and "can't afford it" — the panel's dim
        styling is what tells those apart for the player.
        """
        defn = _BY_KEY.get(key)
        if defn is None:
            return None
        return self.purchase(defn.name)

    def handle_powerup_key(self, key):
        """Activate the bought powerup bound to ``key``; its name, or None.

        None covers both "not a powerup key" and "can't afford it" — the
        same contract as handle_key, with the strip's brightness telling
        the player which. Price escalation and duration timers live in
        the Economy (activate_powerup / tick_powerups); the use counts
        persist through the idle_powerup_uses save seam.
        """
        name = powerup_name_for_key(key)
        if name is None:
            return None
        if not self.economy.activate_powerup(name):
            sound.play(sound.SFX_DENIED)  # extra SFX: can't afford the price
            return None
        return name

    def purchase(self, name):
        """One level of ``name`` through the Economy seams, effects applied."""
        defn = _BY_NAME[name]
        cost = self.economy.upgrade_cost(name)
        if not self.economy.buy(name):
            sound.play(sound.SFX_DENIED)  # extra SFX: can't afford the level
            return None
        self.apply_effects()
        return Purchase(defn.name, defn.title, self.economy.levels[name], cost)

    def affordable(self, name):
        """Whether the ledger can pay the next level right now — the same
        gate buy() enforces, surfaced for the panel's brightness rule."""
        return self.economy.credits >= self.economy.upgrade_cost(name)

    def affordable_powerup(self, name):
        """Whether the ledger can pay this powerup's next (escalated) price
        right now — the panel strip's brightness rule."""
        return self.economy.credits >= self.economy.powerup_price(name)

    # --- panel ------------------------------------------------------------

    def cell_center(self, name):
        """Where this upgrade's confirmation float should rise from."""
        x = (_CELL_INDEX[name] + 0.5) * cell_width()
        return (x, SCREEN_HEIGHT - SHOP_PANEL_HEIGHT)

    def draw_panel(self, screen):
        """Bottom strip: one cell per upgrade — key, title, level, next cost.

        Affordability is the highlight: cells the ledger can already pay
        for glow, the rest sit dim, so the next affordable purchase is
        always the brightest thing on the strip.
        """
        rect = pygame.Rect(
            0, SCREEN_HEIGHT - SHOP_PANEL_HEIGHT, SCREEN_WIDTH, SHOP_PANEL_HEIGHT
        )
        pygame.draw.rect(screen, SHOP_PANEL_BG, rect)
        pygame.draw.line(screen, SHOP_PANEL_BORDER, rect.topleft, rect.topright, 2)
        font = shop_font()
        for defn in UPGRADES:
            level = self.economy.levels[defn.name]
            cost = int(self.economy.upgrade_cost(defn.name))
            color = affordability_color(self.affordable(defn.name))
            x = _CELL_INDEX[defn.name] * cell_width() + SHOP_CELL_PADDING
            y = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT + SHOP_CELL_PADDING
            screen.blit(font.render(f"[{defn.key_label}] {defn.title}  Lv {level}", True, color), (x, y))
            screen.blit(font.render(f"{cost} cr · {defn.effect}", True, color), (x, y + SHOP_LINE_STEP))

    def draw_powerups(self, screen):
        """The powerup strip one line above the shop panel, plus the
        active-effects countdown above it.

        Same visual grammar as the upgrade cells — key, title, next
        price, bright when affordable, dim when not — with the
        escalating per-use price shown live. Running timed effects
        glow in the active color with seconds remaining, soonest
        expiry first: the indicator that tells the player when
        Overdrive ends. Reuses the panel's font and colors; no second
        rendering setup lives anywhere.
        """
        font = shop_font()
        base_y = SCREEN_HEIGHT - SHOP_PANEL_HEIGHT
        actives = self.economy.active_powerups()
        if actives:
            label = " · ".join(
                f"{title} {remaining:.1f}s" for title, remaining in actives
            )
            screen.blit(
                font.render(label, True, POWERUP_ACTIVE_COLOR),
                (SHOP_CELL_PADDING, base_y - 2 * SHOP_LINE_STEP),
            )
        for index, (name, defn) in enumerate(POWERUPS.items()):
            price = int(self.economy.powerup_price(name))
            color = affordability_color(self.affordable_powerup(name))
            key_label = chr(defn["key"])
            x = SHOP_CELL_PADDING + index * cell_width()
            screen.blit(
                font.render(
                    f"[{key_label}] {defn['title']} {price} cr · {defn['desc']}",
                    True,
                    color,
                ),
                (x, base_y - SHOP_LINE_STEP),
            )
