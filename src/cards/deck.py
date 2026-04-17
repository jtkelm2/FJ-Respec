from core.type import Card
from cards.food import food, food_1, food_3, food_7, food_9
from cards.weapons import weapon, weapon_1, weapon_3, weapon_7, weapon_10
from cards.enemies import enemy, guard, enemy_1, enemy_3, enemy_4, enemy_7, enemy_8, enemy_14
from cards.majors import (
    the_fool, the_empress, the_emperor, the_lovers,
    the_hermit, the_wheel_of_fortune, justice, the_hanged_man,
    strength, the_magician, the_chariot, death_card, the_tower,
    judgement, the_world,
)

_FOOD_FACTORIES = {1: food_1, 3: food_3, 7: food_7, 9: food_9}
_WEAPON_FACTORIES = {1: weapon_1, 3: weapon_3, 7: weapon_7, 10: weapon_10}
_ENEMY_FACTORIES = {1: enemy_1, 3: enemy_3, 4: enemy_4, 7: enemy_7, 8: enemy_8, 14: enemy_14}
_MAJOR_FACTORIES = {  # pragma: no mutate
    0: the_fool,
    1: the_magician,
    3: the_empress,
    4: the_emperor,
    6: the_lovers,
    7: the_chariot,
    8: strength,
    9: the_hermit,
    10: the_wheel_of_fortune,
    11: justice,
    12: the_hanged_man,
    13: death_card,
    16: the_tower,
    20: judgement,
    21: the_world,
}


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
    for factory in _MAJOR_FACTORIES.values():
        deck.append(factory())  # pragma: no mutate
    return deck

def guard_deck() -> list[Card]:
    return [guard(lv) for lv in [8, 9, 10, 11] for _ in range(4)]  # pragma: no mutate
