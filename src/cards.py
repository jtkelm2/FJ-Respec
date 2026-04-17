from core.type import (
    Card, CardType, Discard, Trait, TKind, other,
    Action, Resolve, Damage, Refresh, EnsureDeck, Slot2Slot,
    Effect, GameState, Negotiation,
)
from core.engine import do


def food(level: int) -> Card:
    return Card(f"food_{level}", f"Food ({level})", "", level, (CardType.FOOD,), False, False)  # pragma: no mutate

def weapon(level: int) -> Card:
    return Card(f"weapon_{level}", f"Weapon ({level})", "", level, (CardType.WEAPON,), False, False)  # pragma: no mutate

def enemy(level: int) -> Card:
    return Card(f"enemy_{level}", f"Enemy ({level})", "", level, (CardType.ENEMY,), False, False)  # pragma: no mutate

def guard(level: int) -> Card:
    return Card(f"guard_{level}", f"Guard ({level})", "", level, (CardType.ENEMY,), False, False)  # pragma: no mutate

def role_card(good: bool) -> Card:
    if good:
        return Card("human", "Human", "", None, (CardType.EQUIPMENT,), False, False)  # pragma: no mutate
    return Card("???", "???", "", None, (CardType.EQUIPMENT,), False, False)  # pragma: no mutate


# --- Major Arcana with traits --------------------------------------------

# The Fool — On resolve: Look at the top card of the deck and resolve it.

def the_fool() -> Card:
    card = Card(
        "major_0", "The Fool",  # pragma: no mutate
        "On resolve: Look at the top card of the deck and resolve it.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def effect(g: GameState) -> Negotiation:
            p = g.players[resolver]
            yield from do(EnsureDeck(resolver, "the Fool"))(g)  # pragma: no mutate
            if p.is_dead: return
            yield from do(Slot2Slot(p.deck, p.sidebar, "the Fool"))(g)  # pragma: no mutate
            top = p.sidebar.cards[0]
            yield from do(Resolve(resolver, top, "the Fool"))(g)  # pragma: no mutate
        return effect
    card.traits = [Trait.on_resolve("The Fool", card, callback)]  # pragma: no mutate
    return card

def justice() -> Card:
    card = Card(
        "major_11", "Justice",  # pragma: no mutate
        "On resolve: Deal 5 damage to the other player. Put this into the refresh pile.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def effect(g: GameState) -> Negotiation:
            yield from do(Damage(other(resolver), 5, "Justice"))(g)
            yield from do(Refresh(card, resolver, "Justice"))(g)  # pragma: no mutate
        return effect
    card.traits = [Trait.on_resolve("Justice", card, callback).instead()]
    return card