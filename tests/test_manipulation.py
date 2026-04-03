"""
Manipulation phase: swap, dump, force, and post-manipulation mechanics.

Tests private helpers directly for deterministic control over prompt
sequences, plus an integration test for the full simultaneously-driven phase.
"""

from core.type import PID, Card, CardType, Slot
from core.engine import run, do
from helpers import interp
from cards import food, enemy
from phase.setup import create_initial_state
from phase.manipulation import _manipulate, _dump, _post_manipulation


# ---------- _dump ----------

class TestDump:
    """_dump: discard or refresh each hand card. Elusive cards auto-refresh."""

    def test_discard_all(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        c1, c2 = food(1), food(2)
        p.hand.slot(c1, c2)  # hand order: [c2, c1]

        # 0 = Discard for each card
        run(g, _dump(PID.RED), interp(0, 0))

        assert p.hand.is_empty()
        blue_discard = g.players[PID.BLUE].discard
        assert c1 in blue_discard.cards
        assert c2 in blue_discard.cards

    def test_refresh_all(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        c1, c2 = food(3), food(4)
        p.hand.slot(c1, c2)

        # 1 = Refresh for each card
        run(g, _dump(PID.RED), interp(1, 1))

        assert p.hand.is_empty()
        blue_refresh = g.players[PID.BLUE].refresh
        assert c1 in blue_refresh.cards
        assert c2 in blue_refresh.cards

    def test_mix_discard_and_refresh(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        c1, c2, c3 = food(1), food(2), food(3)
        p.hand.slot(c1, c2, c3)  # hand order: [c3, c2, c1]

        # c3: Discard(0), c2: Refresh(1), c1: Discard(0)
        run(g, _dump(PID.RED), interp(0, 1, 0))

        assert c3 in g.players[PID.BLUE].discard.cards
        assert c2 in g.players[PID.BLUE].refresh.cards
        assert c1 in g.players[PID.BLUE].discard.cards

    def test_elusive_auto_refreshes_without_prompt(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        elusive = Card("elu", "Elusive", "", 1, (CardType.FOOD,), True, False)
        normal = food(2)
        p.hand.slot(elusive, normal)  # hand order: [normal, elusive]

        # Only normal card gets a prompt: Discard(0)
        run(g, _dump(PID.RED), interp(0))

        assert p.hand.is_empty()
        assert elusive in g.players[PID.BLUE].refresh.cards
        assert normal in g.players[PID.BLUE].discard.cards

    def test_empty_hand_is_noop(self):
        g = create_initial_state(seed=42)
        run(g, _dump(PID.RED), interp())
        assert g.players[PID.RED].hand.is_empty()


# ---------- _manipulate ----------

class TestManipulate:
    """_manipulate: swap loop + optional force."""

    def test_done_immediately_no_swap(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        mf1, mf2 = food(1), food(2)
        h1 = food(3)
        p.manipulation_field.slot(mf1, mf2)
        p.hand.slot(h1)

        forcing = {'val': False}
        # Options: [mf2.display, mf1.display, "Done"] -> choose 2 (Done)
        # Then force prompt (equipment exists from setup): choose 0 (No)
        run(g, _manipulate(PID.RED, forcing), interp(2, 0))

        assert mf1 in p.manipulation_field.cards
        assert mf2 in p.manipulation_field.cards
        assert h1 in p.hand.cards
        assert not forcing['val']

    def test_swap_one_card(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        mf1 = food(1)
        h1 = food(9)
        p.manipulation_field.slot(mf1)
        p.hand.slot(h1)

        forcing = {'val': False}
        # Choose mf[0] (mf1), then hand[0] (h1), then Done (index 1)
        # Then force prompt (equipment exists from setup): choose 0 (No)
        run(g, _manipulate(PID.RED, forcing), interp(0, 0, 1, 0))

        assert h1 in p.manipulation_field.cards
        assert mf1 in p.hand.cards

    def test_force_discards_equipment_and_sets_flag(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        mf1 = food(1)
        h1 = food(2)
        p.manipulation_field.slot(mf1)
        p.hand.slot(h1)
        equip = p.equipment.cards[0]  # role card from setup

        forcing = {'val': False}
        # Done immediately (1 mf card + Done -> choose 1)
        # Force prompt: ["No", "Discard <equip>"] -> choose 1
        run(g, _manipulate(PID.RED, forcing), interp(1, 1))

        assert forcing['val']
        assert equip in p.discard.cards
        assert equip not in p.equipment.cards


# ---------- _post_manipulation ----------

class TestPostManipulation:

    def test_deals_card_to_opponent_action_field(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        mf1, mf2 = food(1), food(2)
        p.manipulation_field.slot(mf1, mf2)
        # mf will have 2 + 1 drawn = 3 cards; 4 open action slots
        # -> 3 cards dealt, 1 slot empty, 0 remaining to refresh

        run(g, _post_manipulation(PID.RED, False), interp())

        filled = [s for s in other_p.action_field.slots_in_fill_order()
                  if not s.is_empty()]
        assert len(filled) == 3
        assert p.manipulation_field.is_empty()

    def test_refreshes_remaining_when_all_slots_full(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        # Fill opponent's action field so nothing can be dealt
        for slot in other_p.action_field.slots_in_fill_order():
            slot.slot(food(99))

        mf1 = food(7)
        p.manipulation_field.slot(mf1)
        # mf has 1 + 1 drawn = 2 cards, 0 open slots -> both refreshed

        run(g, _post_manipulation(PID.RED, False), interp())

        assert p.manipulation_field.is_empty()
        # Cards end up in opponent's refresh pile
        assert len(other_p.refresh.cards) >= 2

    def test_force_lets_player_choose_card_to_deal(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        mf1 = food(1)
        p.manipulation_field.slot(mf1)
        # Fill 3 of 4 opponent action slots -> 1 open
        for i, slot in enumerate(other_p.action_field.slots_in_fill_order()):
            if i < 3:
                slot.slot(food(90 + i))
        # mf: 1 + 1 drawn = 2 cards, 1 open slot, forcing -> prompt to choose
        run(g, _post_manipulation(PID.RED, True), interp(0))

        filled = [s for s in other_p.action_field.slots_in_fill_order()
                  if not s.is_empty()]
        assert len(filled) == 4  # all slots now occupied

    def test_refreshes_remaining_with_multiple_cards(self):
        """When 3+ mf cards remain, ALL must be refreshed (not just every other).

        This tests for the list-mutation-during-iteration bug:
        `for card in slot.cards` while do(Refresh(...)) removes from that list.
        """
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        # Fill ALL opponent action slots
        for slot in other_p.action_field.slots_in_fill_order():
            slot.slot(food(99))

        # Put 2 cards in mf; +1 drawn = 3 to refresh
        mf1, mf2 = food(7), food(8)
        p.manipulation_field.slot(mf1, mf2)

        run(g, _post_manipulation(PID.RED, False), interp())

        # Correct behavior: mf should be completely empty
        assert p.manipulation_field.is_empty(), (
            f"Expected empty manipulation field, but {len(p.manipulation_field.cards)} "
            f"card(s) remain. Likely list-mutation-during-iteration bug in "
            f"_post_manipulation step 4."
        )


# ---------- integration ----------

class TestManipulationPhaseIntegration:

    def test_both_dump_empty_hands(self):
        """Both players dump with empty hands; post-manipulation runs cleanly."""
        g = create_initial_state(seed=42)
        initial_red = len(g.players[PID.RED].deck.cards)
        initial_blue = len(g.players[PID.BLUE].deck.cards)

        from phase.manipulation import manipulation_phase
        run(g, manipulation_phase(), interp(1, blue=[1]))

        # Each deck lost 1 card (drawn by opponent's post-manipulation)
        assert len(g.players[PID.RED].deck.cards) == initial_red - 1
        assert len(g.players[PID.BLUE].deck.cards) == initial_blue - 1

        # Each action field has exactly 1 card
        for pid in [PID.RED, PID.BLUE]:
            af = g.players[pid].action_field
            total = sum(len(s.cards) for s in af.slots_in_fill_order())
            assert total == 1

        # Manipulation fields emptied
        assert g.players[PID.RED].manipulation_field.is_empty()
        assert g.players[PID.BLUE].manipulation_field.is_empty()
