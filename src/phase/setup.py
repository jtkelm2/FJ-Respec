import random
from core.type import *
from cards import *

def create_initial_state(seed: int | None = None) -> GameState:
    rng = random.Random(seed)

    red_deck  = _player_deck()
    blue_deck = _player_deck()
    guards    = _guard_deck()

    rng.shuffle(red_deck)
    rng.shuffle(blue_deck)
    rng.shuffle(guards)

    roles = [
        (role_card(good=True),  DefaultRole(good=True)),
        (role_card(good=True),  DefaultRole(good=True)),
        (role_card(good=False), DefaultRole(good=False)),
    ]
    rng.shuffle(roles)

    red_card, red_role   = roles[0]
    blue_card, blue_role = roles[1]

    red = PlayerState(alignment=red_role.alignment, role=red_role, deck=red_deck)
    red.equipment[0].cards.append(red_card)

    blue = PlayerState(alignment=blue_role.alignment, role=blue_role, deck=blue_deck)
    blue.equipment[0].cards.append(blue_card)

    return GameState(
        rng=rng,
        priority=rng.choice([PID.RED, PID.BLUE]),
        players={PID.RED: red, PID.BLUE: blue},
        guard_deck=guards,
        action_field=ActionField(),
    )


def _player_deck() -> list[Card]:
    deck: list[Card] = []
    for lv in range(1, 11):  deck.append(food(lv))
    for lv in range(1, 11):  deck.append(weapon(lv))
    for lv in range(1, 15):
        deck.append(enemy(lv))
        deck.append(enemy(lv))
    return deck

def _guard_deck() -> list[Card]:
    return [guard(lv) for lv in [8, 9, 10, 11] for _ in range(4)]