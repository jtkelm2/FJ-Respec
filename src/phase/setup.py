import random
from core.type import *
from core.engine import do
from cards.roles import GOOD_ROLES, EVIL_ROLES
from cards.deck import player_deck, guard_deck


def create_initial_state(seed: int | None = None) -> GameState:
    """Pure: shuffle decks, seed RNG, pick priority, populate role pool.

    No role assignment, no generator-driven mutations. The role cards
    are assigned later by setup_phase(), which runs inside the real
    interpreter so on_role_assign traits can yield prompts."""
    rng = random.Random(seed)  # pragma: no mutate

    red_deck  = player_deck()
    blue_deck = player_deck()
    guards    = guard_deck()

    rng.shuffle(red_deck)
    rng.shuffle(blue_deck)
    rng.shuffle(guards)

    red = PlayerState(PID.RED)
    red.deck.slot(*red_deck)

    blue = PlayerState(PID.BLUE)
    blue.deck.slot(*blue_deck)

    g = GameState(
        rng=rng,
        priority=rng.choice([PID.RED, PID.BLUE]),  # pragma: no mutate
        players={PID.RED: red, PID.BLUE: blue},
        guard_deck=Slot("guard_deck", SlotKind.GUARD_DECK, cards=guards),  # pragma: no mutate
        role_pool=list(GOOD_ROLES + EVIL_ROLES),
    )

    return g


def setup_phase(picks: dict[PID, tuple[Card, Role]] | None = None) -> Effect:
    """Decide alignments, pick roles from g.role_pool, dispatch AssignRoleCard.

    If `picks` is provided, it overrides the random selection for the given
    players — useful for tests and replay-driven setup. Unspecified players
    still roll randomly using g.rng."""
    def effect(g: GameState) -> Negotiation:
        alignments = [Alignment.GOOD, Alignment.GOOD, Alignment.EVIL]  # pragma: no mutate
        g.rng.shuffle(alignments)
        for pid, alignment in zip([PID.RED, PID.BLUE], alignments[:2]):  # pragma: no mutate
            if picks is not None and pid in picks:
                card, role = picks[pid]
            else:
                pool = [(f, r) for f, r in g.role_pool if r.alignment == alignment]
                factory, role = g.rng.choice(pool)
                card = factory()
            yield from do(AssignRoleCard(card, role, pid, "setup"))(g)  # pragma: no mutate
    return effect
