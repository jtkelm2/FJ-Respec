from core.type import (
    Card, CardType, Trait,
    Action, Discard, Damage, PID, other,
    Effect, GameState, Negotiation,
    PromptBuilder, TextOption, CardOption,
)
from core.engine import do


def weapon(level: int) -> Card:
    return Card(f"weapon_{level}", f"Weapon ({level})", "", level, (CardType.WEAPON,), False, False)  # pragma: no mutate


# weapon_3 (Piñata Stick) — On discard: You may deal 3 damage to the other
# player in order to see their hand.

def weapon_3() -> Card:
    card = Card(
        "weapon_3", "Piñata Stick (3)",  # pragma: no mutate
        "On discard: You may deal 3 damage to the other player in order to see their hand.",  # pragma: no mutate
        3, (CardType.WEAPON,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Discard)
        discarder = a.discarder
        def eff(g: GameState) -> Negotiation:
            opp = other(discarder)
            pb = (PromptBuilder("Piñata Stick: deal 3 damage to see opponent's hand?")  # pragma: no mutate
                  .add(TextOption("Yes"))  # pragma: no mutate
                  .add(TextOption("No")))  # pragma: no mutate
            response = yield pb.build(discarder)
            if response[discarder] == TextOption("Yes"):
                yield from do(Damage(opp, 3, "Piñata Stick"))(g)  # pragma: no mutate
                opp_hand = g.players[opp].hand.cards
                pb2 = PromptBuilder("Opponent's hand:")  # pragma: no mutate
                for c in opp_hand:
                    pb2.context(CardOption(c))
                pb2.add(TextOption("OK"))  # pragma: no mutate
                yield pb2.build(discarder)
        return eff
    card.traits = [Trait.on_discard(card, callback)]
    return card
