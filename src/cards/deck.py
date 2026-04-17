from core.type import Card
from cards.food import food
from cards.weapons import weapon
from cards.enemies import enemy, guard


def player_deck() -> list[Card]:
    deck: list[Card] = []
    for lv in range(1, 11):  deck.append(food(lv))  # pragma: no mutate
    for lv in range(1, 11):  deck.append(weapon(lv))  # pragma: no mutate
    for lv in range(1, 15):  # pragma: no mutate
        deck.append(enemy(lv))  # pragma: no mutate
        deck.append(enemy(lv))  # pragma: no mutate
    return deck

def guard_deck() -> list[Card]:
    return [guard(lv) for lv in [8, 9, 10, 11] for _ in range(4)]  # pragma: no mutate
