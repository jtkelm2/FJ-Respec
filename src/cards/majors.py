from core.type import (
    Card, CardType, Trait, other,
    Action, Resolve, Damage, Refresh, EnsureDeck, Slot2Slot,
    Effect, GameState, Negotiation,
)
from core.engine import do


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
    card.traits = [Trait.on_resolve(card, callback)]  # pragma: no mutate
    return card


# Justice — On resolve: Deal 5 damage to the other player. Put this into
# the refresh pile.

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
    card.traits = [Trait.on_resolve(card, callback).instead()]
    return card
