from core.type import Card, CardType

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