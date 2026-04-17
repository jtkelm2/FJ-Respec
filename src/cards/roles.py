from core.type import (
    Card, CardType, Trait, TKind, PID, Phase,
    Action, Damage, Heal, Eat, Wield, Resolve,
    EndPhase, SetHP,
    Effect, GameState, Negotiation,
)
from core.engine import do


def role_card(good: bool) -> Card:
    if good:
        return Card("human", "Human", "", None, (CardType.EQUIPMENT,), False, False)  # pragma: no mutate
    return Card("???", "???", "", None, (CardType.EQUIPMENT,), False, False)  # pragma: no mutate


# --- Foo(d) Fighter (bad_role_3) -----------------------------------------
# Whenever you would wield a weapon, instead eat it as food.
# Whenever you would eat food, instead wield it as a weapon.

def food_fighter() -> Card:
    card = Card(
        "food_fighter", "Foo(d) Fighter",  # pragma: no mutate
        "Whenever you would wield a weapon, instead eat it as food.\n"  # pragma: no mutate
        "Whenever you would eat food, instead wield it as a weapon.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,), False, False,
    )
    def wield_to_eat(a: Action) -> Effect:
        assert isinstance(a, Wield)
        return do(Eat(a.player, a.card, "Foo(d) Fighter"))

    def eat_to_wield(a: Action) -> Effect:
        assert isinstance(a, Eat)
        return do(Wield(a.player, a.card, "Foo(d) Fighter"))

    card.traits = [
        Trait.while_equipped(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Wield),
            wield_to_eat),
        Trait.while_equipped(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Eat),
            eat_to_wield),
    ]
    return card


# --- Corruption (bad_role_4) ---------------------------------------------
# Heal 6HP per turn at the end of your Refresh Phase.
# Whenever you would heal by any other means, instead take that much damage.

def corruption() -> Card:
    card = Card(
        "corruption", "Corruption",  # pragma: no mutate
        "Heal 6HP per turn at the end of your Refresh Phase.\n"  # pragma: no mutate
        "Whenever you would heal by any other means, instead take that much damage.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,), False, False,
    )
    # Heal at end of refresh
    def refresh_cb(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            for pid in PID:
                if card.slot is g.players[pid].equipment:
                    yield from do(SetHP(pid, g.players[pid].hp + 6, "Corruption"))(g)
                    return
        return eff

    # Replace non-Corruption heals with damage
    def heal_flip(a: Action) -> Effect:
        assert isinstance(a, Heal)
        return do(Damage(a.target, a.amount, "Corruption"))

    card.traits = [
        Trait.while_equipped(card, TKind.AFTER,
            lambda a: isinstance(a, EndPhase) and a.phase == Phase.REFRESH,
            refresh_cb),
        Trait.while_equipped(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Heal) and a.source != "Corruption",
            heal_flip),
    ]
    return card


# --- The Poet (bad_role_6) -----------------------------------------------
# When you would fight a non-guard enemy, you may choose to refresh it instead.
# Your weapons discard on first use.

def the_poet() -> Card:
    card = Card(
        "the_poet", "The Poet",  # pragma: no mutate
        "When you would fight a non-guard enemy, you may choose to refresh it instead.\n"  # pragma: no mutate
        "Your weapons discard on first use.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,), False, False,
    )
    from core.type import Slay, Discard, Refresh as RefreshAction, PromptBuilder, TextOption

    # Weapons discard on first use: AFTER any Slay with weapon, discard the weapon.
    def weapon_discard_cb(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            if a.ws is not None and a.ws.weapon is not None:
                yield from do(Discard(a.slayer, a.ws.weapon, "The Poet"))(g)  # pragma: no mutate
                for c in list(a.ws.killstack.cards):
                    yield from do(Discard(a.slayer, c, "The Poet kill pile"))(g)  # pragma: no mutate
        return eff

    card.traits = [
        Trait.while_equipped(card, TKind.AFTER,
            lambda a: isinstance(a, Slay) and a.ws is not None,
            weapon_discard_cb),
    ]
    return card
