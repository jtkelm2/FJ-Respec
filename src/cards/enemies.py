from core.type import Card, CardType


def enemy(level: int) -> Card:
    return Card(f"enemy_{level}", f"Enemy ({level})", "", level, (CardType.ENEMY,), False, False)  # pragma: no mutate

def guard(level: int) -> Card:
    return Card(f"guard_{level}", f"Guard ({level})", "", level, (CardType.ENEMY,), False, False)  # pragma: no mutate
