from core.type import Card, CardType


def weapon(level: int) -> Card:
    return Card(f"weapon_{level}", f"Weapon ({level})", "", level, (CardType.WEAPON,), False, False)  # pragma: no mutate
