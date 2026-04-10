import random
from core.type import *
from cards import *

def create_initial_state(seed: int | None = None) -> GameState:
    rng = random.Random(seed)  # pragma: no mutate

    red_deck  = _player_deck()
    blue_deck = _player_deck()
    guards    = _guard_deck()

    rng.shuffle(red_deck)
    rng.shuffle(blue_deck)
    rng.shuffle(guards)

    roles = [  # pragma: no mutate
        (role_card(good=True),  DefaultRole(good=True)),  # pragma: no mutate
        (role_card(good=True),  DefaultRole(good=True)),  # pragma: no mutate
        (role_card(good=False), DefaultRole(good=False)),  # pragma: no mutate
    ]
    rng.shuffle(roles)

    red_card, red_role   = roles[0]
    blue_card, blue_role = roles[1]

    red = PlayerState("red", alignment=red_role.alignment, role=red_role)  # pragma: no mutate
    red.deck.slot(*red_deck)
    red.equipment.slot(red_card)

    blue = PlayerState("blue", alignment=blue_role.alignment, role=blue_role)  # pragma: no mutate
    blue.deck.slot(*blue_deck)
    blue.equipment.slot(blue_card)

    return GameState(
        rng=rng,
        priority=rng.choice([PID.RED, PID.BLUE]),  # pragma: no mutate
        players={PID.RED: red, PID.BLUE: blue},
        guard_deck=Slot("guard_deck", guards),  # pragma: no mutate
        action_field=ActionField("shared"),
    )


def _player_deck() -> list[Card]:
    deck: list[Card] = []
    for lv in range(1, 11):  deck.append(food(lv))  # pragma: no mutate
    for lv in range(1, 11):  deck.append(weapon(lv))  # pragma: no mutate
    for lv in range(1, 15):  # pragma: no mutate
        deck.append(enemy(lv))  # pragma: no mutate
        deck.append(enemy(lv))  # pragma: no mutate
    return deck

def _guard_deck() -> list[Card]:
    return [guard(lv) for lv in [8, 9, 10, 11] for _ in range(4)]  # pragma: no mutate
