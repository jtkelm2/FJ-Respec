import random
from core.type import *
from core.engine import do
from interact.interpret import run, AggregateInterpreter
from interact.player import ScriptedPlayer
from cards.roles import GOOD_ROLES, EVIL_ROLES
from cards.deck import player_deck, guard_deck

def create_initial_state(seed: int | None = None, vanilla_roles: bool = False) -> GameState:
    rng = random.Random(seed)  # pragma: no mutate

    red_deck  = player_deck()
    blue_deck = player_deck()
    guards    = guard_deck()

    rng.shuffle(red_deck)
    rng.shuffle(blue_deck)
    rng.shuffle(guards)

    # Alignment assignment: [Good, Good, Evil], shuffled, first two drawn.
    # Same probability as before: each player 2/3 Good, 1/3 Evil, at most one Evil.
    alignments = [Alignment.GOOD, Alignment.GOOD, Alignment.EVIL]  # pragma: no mutate
    rng.shuffle(alignments)
    red_alignment  = alignments[0]
    blue_alignment = alignments[1]

    # Uniform random role within the assigned alignment.
    def _pick_role(alignment):
        if vanilla_roles:
            from cards.roles import role_card
            return role_card(good=(alignment == Alignment.GOOD)), \
                   DefaultRole(good=(alignment == Alignment.GOOD))
        pool = GOOD_ROLES if alignment == Alignment.GOOD else EVIL_ROLES
        factory, role = rng.choice(pool)
        return factory(), role

    red_card, red_role   = _pick_role(red_alignment)
    blue_card, blue_role = _pick_role(blue_alignment)

    red = PlayerState("red", alignment=red_alignment, role=red_role)  # pragma: no mutate
    red.deck.slot(*red_deck)

    blue = PlayerState("blue", alignment=blue_alignment, role=blue_role)  # pragma: no mutate
    blue.deck.slot(*blue_deck)

    g = GameState(
        rng=rng,
        priority=rng.choice([PID.RED, PID.BLUE]),  # pragma: no mutate
        players={PID.RED: red, PID.BLUE: blue},
        guard_deck=Slot("guard_deck", SlotKind.GUARD_DECK, guards),  # pragma: no mutate
        action_field=ActionField("shared"),
    )

    # Assign role cards through the action system so on_role_assign traits fire
    _noop = AggregateInterpreter(ScriptedPlayer([]), ScriptedPlayer([]))
    run(g, do(AssignRoleCard(red_card, PID.RED, "setup")), _noop)  # pragma: no mutate
    run(g, do(AssignRoleCard(blue_card, PID.BLUE, "setup")), _noop)  # pragma: no mutate

    return g
