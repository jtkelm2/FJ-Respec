import random
from core.type import *
from cards import role_card
from cards.deck import player_deck, guard_deck

def create_initial_state(seed: int | None = None) -> GameState:
    rng = random.Random(seed)  # pragma: no mutate

    red_deck  = player_deck()
    blue_deck = player_deck()
    guards    = guard_deck()

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
        guard_deck=Slot("guard_deck", SlotKind.GUARD_DECK, guards),  # pragma: no mutate
        action_field=ActionField("shared"),
    )
