from core.type import Card, CardType


def food(level: int) -> Card:
    return Card(f"food_{level}", f"Food ({level})", "", level, (CardType.FOOD,), False, False)  # pragma: no mutate
