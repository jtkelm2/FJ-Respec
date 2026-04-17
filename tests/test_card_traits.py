"""
End-to-end demonstrations of two real cards routed through the trait system:
The Fool (ON_RESOLVE BEFORE) and Justice (ON_RESOLVE REPLACEMENT).
"""

from core.type import (
    PID, Card, CardType, Slot, Trait, TKind, TextOption,
    Resolve, Damage, Action, GameState, Effect, Negotiation,
)
from core.engine import do
from interact.interpret import run
from helpers import interp, minimal_game, count_all_cards
from cards import the_fool, justice, food


# --- The Fool ------------------------------------------------------------

class TestCardShape:
    """Cheap assertions on factory-produced cards' static fields, so flag
    mutations (is_elusive False -> True, etc.) get caught."""

    def test_the_fool_flags(self):
        c = the_fool()
        assert c.is_elusive is False
        assert c.is_first is False
        assert c.types == (CardType.EVENT,)
        assert c.level is None

    def test_justice_flags(self):
        c = justice()
        assert c.is_elusive is False
        assert c.is_first is False
        assert c.types == (CardType.EVENT,)
        assert c.level is None


class TestTheFool:

    def test_resolves_top_of_deck(self):
        """The Fool's BEFORE trait peels the top of deck and resolves it,
        then the card itself is discarded by the default Resolve(EVENT) path."""
        g = minimal_game()
        fool = the_fool()
        snack = food(5)
        g.players[PID.RED].action_field.top_distant.slot(fool)
        g.players[PID.RED].deck.slot(snack)
        g.players[PID.RED].hp = 5
        before = count_all_cards(g)

        run(g, do(Resolve(PID.RED, fool, "test")), interp())

        assert g.players[PID.RED].hp == 10  # ate the food (5 -> 10)
        assert g.players[PID.RED].is_satiated
        assert fool in g.players[PID.RED].discard.cards
        assert snack in g.players[PID.RED].discard.cards
        assert count_all_cards(g) == before

    def test_exhaustion_when_deck_and_refresh_empty(self):
        """If The Fool fires with nothing to draw, EnsureDeck triggers a
        mutual death; the trait body bails before attempting Slot2Slot."""
        g = minimal_game()
        fool = the_fool()
        g.players[PID.RED].action_field.top_distant.slot(fool)
        # decks and refresh piles default empty in minimal_game

        run(g, do(Resolve(PID.RED, fool, "test")), interp())

        assert g.players[PID.RED].is_dead
        assert g.players[PID.BLUE].is_dead


# --- Justice (Way A: REPLACEMENT) ----------------------------------------

class TestJustice:

    def test_damages_opponent_and_refreshes_self(self):
        """Justice's REPLACEMENT shadows the default Resolve(EVENT) -> Discard.
        Effect: opp -5 HP, Justice ends in resolver's REFRESH (not discard)."""
        g = minimal_game()
        j = justice()
        g.players[PID.RED].action_field.top_distant.slot(j)
        g.players[PID.RED].hp = 20
        g.players[PID.BLUE].hp = 20
        before = count_all_cards(g)

        run(g, do(Resolve(PID.RED, j, "test")), interp())

        assert g.players[PID.BLUE].hp == 15
        assert g.players[PID.RED].hp == 20
        assert j in g.players[PID.RED].refresh.cards
        assert j not in g.players[PID.RED].discard.cards
        assert count_all_cards(g) == before

    def test_blue_resolving_red_slot_damages_red(self):
        """The trait body uses action.resolver, not the slot owner — so when
        BLUE resolves a Justice sitting on RED's field, RED takes the damage
        and Justice goes to BLUE's refresh."""
        g = minimal_game()
        j = justice()
        g.players[PID.RED].action_field.top_distant.slot(j)
        g.players[PID.RED].hp = 20
        g.players[PID.BLUE].hp = 20

        run(g, do(Resolve(PID.BLUE, j, "test")), interp())

        assert g.players[PID.RED].hp == 15
        assert g.players[PID.BLUE].hp == 20
        assert j in g.players[PID.BLUE].refresh.cards

    def test_competing_replacement_prompts_chooser(self):
        """When Justice's REPLACEMENT and a synthetic REPLACEMENT both apply
        to the same Resolve, the priority player chooses between them."""
        g = minimal_game()
        j = justice()
        g.players[PID.RED].action_field.top_distant.slot(j)

        # Synthetic REPLACEMENT on the same Resolve(j): does nothing (no-op).
        def noop_callback(a):
            def eff(g):
                return
                yield  # pragma: no cover
            return eff
        g.active_traits.append(
            Trait("noop_resolve", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Resolve) and a.card is j,
                  noop_callback)
        )
        g.players[PID.RED].hp = 20
        g.players[PID.BLUE].hp = 20

        # priority defaults to RED in minimal_game; RED picks the noop.
        run(g, do(Resolve(PID.RED, j, "test")),
            interp(TextOption("noop_resolve")))

        assert g.players[PID.BLUE].hp == 20  # Justice did NOT fire
        assert j not in g.players[PID.RED].refresh.cards
        assert j not in g.players[PID.RED].discard.cards
