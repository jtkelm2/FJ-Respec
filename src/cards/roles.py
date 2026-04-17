from core.type import Card, CardType


def role_card(good: bool) -> Card:
    if good:
        return Card("human", "Human", "", None, (CardType.EQUIPMENT,), False, False)  # pragma: no mutate
    return Card("???", "???", "", None, (CardType.EQUIPMENT,), False, False)  # pragma: no mutate
