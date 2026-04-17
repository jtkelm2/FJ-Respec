from core.type import (
    Card, CardType, Trait, TKind,
    Action, Eat, Damage,
    Effect, GameState, Negotiation,
)
from core.engine import do


def food(level: int) -> Card:
    return Card(f"food_{level}", f"Food ({level})", "", level, (CardType.FOOD,), False, False)  # pragma: no mutate


# food_1 — On resolve: After eating, receive d10 damage.

def food_1() -> Card:
    card = Card(
        "food_1", "Food? (5)",  # pragma: no mutate
        "On resolve: After eating, receive d10 damage.",  # pragma: no mutate
        5, (CardType.FOOD,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Eat)
        def eff(g: GameState) -> Negotiation:
            dmg = g.rng.randint(1, 10)
            yield from do(Damage(a.player, dmg, "food_1"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait(f"{card.display_name} (After Eat)", TKind.AFTER,  # pragma: no mutate
                         lambda a: isinstance(a, Eat) and a.card is card,
                         callback)]
    return card
