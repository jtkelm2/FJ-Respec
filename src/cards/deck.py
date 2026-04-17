from core.type import Card
from cards.food import food, food_1
from cards.weapons import weapon, weapon_3
from cards.enemies import enemy, guard, enemy_3, enemy_7, enemy_14

_FOOD_FACTORIES = {1: food_1}
_WEAPON_FACTORIES = {3: weapon_3}
_ENEMY_FACTORIES = {3: enemy_3, 7: enemy_7, 14: enemy_14}


def player_deck() -> list[Card]:
    deck: list[Card] = []
    for lv in range(1, 11):  # pragma: no mutate
        f = _FOOD_FACTORIES.get(lv)
        deck.append(f() if f else food(lv))  # pragma: no mutate
    for lv in range(1, 11):  # pragma: no mutate
        f = _WEAPON_FACTORIES.get(lv)
        deck.append(f() if f else weapon(lv))  # pragma: no mutate
    for lv in range(1, 15):  # pragma: no mutate
        f = _ENEMY_FACTORIES.get(lv)
        deck.append(f() if f else enemy(lv))  # pragma: no mutate
        deck.append(f() if f else enemy(lv))  # pragma: no mutate
    return deck

def guard_deck() -> list[Card]:
    return [guard(lv) for lv in [8, 9, 10, 11] for _ in range(4)]  # pragma: no mutate
