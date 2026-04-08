"""
Manipulation phase: swap, dump, force, and post-manipulation mechanics.

Tests private helpers directly for deterministic control over prompt
sequences, plus an integration test for the full simultaneously-driven phase.
"""

from core.type import PID, Card, CardType, Slot, TextOption, CardOption
from core.engine import do
from interact.interpret import run
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

        run(g, _dump(PID.RED), interp(TextOption("Discard"), TextOption("Discard")))

        assert p.hand.is_empty()
        blue_discard = g.players[PID.BLUE].discard
        assert c1 in blue_discard.cards
        assert c2 in blue_discard.cards

    def test_refresh_all(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        c1, c2 = food(3), food(4)
        p.hand.slot(c1, c2)

        run(g, _dump(PID.RED), interp(TextOption("Refresh"), TextOption("Refresh")))

        assert p.hand.is_empty()
        blue_refresh = g.players[PID.BLUE].refresh
        assert c1 in blue_refresh.cards
        assert c2 in blue_refresh.cards

    def test_mix_discard_and_refresh(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        c1, c2, c3 = food(1), food(2), food(3)
        p.hand.slot(c1, c2, c3)  # hand order: [c3, c2, c1]

        run(g, _dump(PID.RED), interp(TextOption("Discard"), TextOption("Refresh"), TextOption("Discard")))

        assert c3 in g.players[PID.BLUE].discard.cards
        assert c2 in g.players[PID.BLUE].refresh.cards
        assert c1 in g.players[PID.BLUE].discard.cards

    def test_elusive_auto_refreshes_without_prompt(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        elusive = Card("elu", "Elusive", "", 1, (CardType.FOOD,), True, False)
        normal = food(2)
        p.hand.slot(elusive, normal)  # hand order: [normal, elusive]

        run(g, _dump(PID.RED), interp(TextOption("Discard")))

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
        p.sidebar.slot(mf1, mf2)
        p.hand.slot(h1)

        forcing = {'val': False}
        run(g, _manipulate(PID.RED, forcing), interp(TextOption("Done"), TextOption("No")))

        assert mf1 in p.sidebar.cards
        assert mf2 in p.sidebar.cards
        assert h1 in p.hand.cards
        assert not forcing['val']

    def test_swap_one_card(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        mf1 = food(1)
        h1 = food(9)
        p.sidebar.slot(mf1)
        p.hand.slot(h1)

        forcing = {'val': False}
        run(g, _manipulate(PID.RED, forcing), interp(CardOption(mf1), CardOption(h1), TextOption("Done"), TextOption("No")))

        assert h1 in p.sidebar.cards
        assert mf1 in p.hand.cards

    def test_force_discards_equipment_and_sets_flag(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        mf1 = food(1)
        h1 = food(2)
        p.sidebar.slot(mf1)
        p.hand.slot(h1)
        equip = p.equipment.cards[0]  # role card from setup

        forcing = {'val': False}
        run(g, _manipulate(PID.RED, forcing), interp(TextOption("Done"), CardOption(equip)))

        assert forcing['val']
        assert equip in p.discard.cards
        assert equip not in p.equipment.cards

    def test_force_with_second_equipment_discards_correct_one(self):
        """Kills mutant: equipment_cards[choice-1] -> equipment_cards[choice-2].

        With 2 equipment cards and choice=2, choice-1=1 (correct second card)
        vs choice-2=0 (wrong first card).
        """
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        mf1 = food(1)
        h1 = food(2)
        p.sidebar.slot(mf1)
        p.hand.slot(h1)

        extra_equip = Card("shield", "Shield", "", None, (CardType.EQUIPMENT,), False, False)
        p.equipment.slot(extra_equip)
        role_card = [c for c in p.equipment.cards if c is not extra_equip][0]

        forcing = {'val': False}
        run(g, _manipulate(PID.RED, forcing), interp(TextOption("Done"), CardOption(role_card)))

        assert forcing['val']
        assert role_card in p.discard.cards
        assert extra_equip in p.equipment.cards  # first one NOT discarded


# ---------- _post_manipulation ----------

class TestPostManipulation:

    def test_deals_card_to_opponent_action_field(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)

        run(g, _post_manipulation(PID.RED, False), interp())

        filled = [s for s in other_p.action_field.slots_in_fill_order()
                  if not s.is_empty()]
        assert len(filled) == 3
        assert p.sidebar.is_empty()

    def test_refreshes_remaining_when_all_slots_full(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        for slot in other_p.action_field.slots_in_fill_order():
            slot.slot(food(99))

        mf1 = food(7)
        p.sidebar.slot(mf1)

        run(g, _post_manipulation(PID.RED, False), interp())

        assert p.sidebar.is_empty()
        assert len(other_p.refresh.cards) >= 2

    def test_force_lets_player_choose_card_to_deal(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        mf1 = food(1)
        p.sidebar.slot(mf1)
        for i, slot in enumerate(other_p.action_field.slots_in_fill_order()):
            if i < 3:
                slot.slot(food(90 + i))
        run(g, _post_manipulation(PID.RED, True), interp(CardOption(mf1)))

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

        for slot in other_p.action_field.slots_in_fill_order():
            slot.slot(food(99))

        mf1, mf2 = food(7), food(8)
        p.sidebar.slot(mf1, mf2)

        run(g, _post_manipulation(PID.RED, False), interp())

        assert p.sidebar.is_empty(), (
            f"Expected empty manipulation field, but {len(p.sidebar.cards)} "
            f"card(s) remain. Likely list-mutation-during-iteration bug in "
            f"_post_manipulation step 4."
        )


# ---------- integration ----------

class TestManipulationPhaseIntegration:

    def test_manipulate_with_force_reaches_post_manipulation(self):
        """Kills mutant: forcing['val'] -> None in manipulation_phase.

        With forcing=True, post-manipulation gives a prompt to choose which
        card to send. With forcing=False (the mutant), Slot2Slot takes the
        first card from the shuffled mf without asking.

        We verify forcing by checking that equipment was discarded (force cost)
        AND that the number of interpreter choices consumed matches the forcing
        path (which has one extra prompt).
        """
        g = create_initial_state(seed=42)
        red = g.players[PID.RED]
        blue = g.players[PID.BLUE]

        mf1 = food(1)
        h1 = food(2)
        red.sidebar.slot(mf1)
        red.hand.slot(h1)

        for i, slot in enumerate(blue.action_field.slots_in_fill_order()):
            if i < 3:
                slot.slot(food(90 + i))

        from phase.manipulation import manipulation_phase
        from interact.player import ScriptedInterpreter
        from interact.interpret import AggregateInterpreter

        equip = red.equipment.cards[0]
        red_script = ScriptedInterpreter([TextOption("Manipulate"), TextOption("Done"), CardOption(equip), CardOption(mf1)])
        blue_script = ScriptedInterpreter([TextOption("Dump")])
        run(g, manipulation_phase(),
            AggregateInterpreter(red_script, blue_script))

        assert len(red.equipment.cards) == 0

        filled = [s for s in blue.action_field.slots_in_fill_order()
                  if not s.is_empty()]
        assert len(filled) == 4

        assert len(red_script.script) == 0, (
            f"RED interpreter has {len(red_script.script)} unconsumed choice(s). "
            f"Forcing prompt was likely skipped (forcing flag lost)."
        )

    def test_both_dump_empty_hands(self):
        """Both players dump with empty hands; post-manipulation runs cleanly."""
        g = create_initial_state(seed=42)
        initial_red = len(g.players[PID.RED].deck.cards)
        initial_blue = len(g.players[PID.BLUE].deck.cards)

        from phase.manipulation import manipulation_phase
        run(g, manipulation_phase(), interp(TextOption("Dump"), blue=[TextOption("Dump")]))

        assert len(g.players[PID.RED].deck.cards) == initial_red - 1
        assert len(g.players[PID.BLUE].deck.cards) == initial_blue - 1

        for pid in [PID.RED, PID.BLUE]:
            af = g.players[pid].action_field
            total = sum(len(s.cards) for s in af.slots_in_fill_order())
            assert total == 1

        assert g.players[PID.RED].sidebar.is_empty()
        assert g.players[PID.BLUE].sidebar.is_empty()
