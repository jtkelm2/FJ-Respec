"""
Manipulation phase: swap, dump, force, and post-manipulation mechanics.

Tests private helpers directly for deterministic control over prompt
sequences, plus an integration test for the full simultaneously-driven phase.
"""

from core.type import PID, Card, CardType, Slot, TextOption, CardOption, PostManipulated, PostManipulate
from core.engine import do
from interact.interpret import run
from helpers import interp, initial_game
from cards import food, enemy
from phase.manipulation import _manipulate, _dump, _post_manipulation


# ---------- _dump ----------

class TestDump:
    """_dump: discard or refresh each hand card. Elusive cards auto-refresh."""

    def test_discard_all(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        c1, c2 = food(1), food(2)
        p.hand.slot(c1, c2)  # hand order: [c2, c1]

        run(g, _dump(PID.RED), interp(TextOption("Discard"), TextOption("Discard")))

        assert p.hand.is_empty()
        blue_discard = g.players[PID.BLUE].discard
        assert c1 in blue_discard.cards
        assert c2 in blue_discard.cards

    def test_refresh_all(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        c1, c2 = food(3), food(4)
        p.hand.slot(c1, c2)

        run(g, _dump(PID.RED), interp(TextOption("Refresh"), TextOption("Refresh")))

        assert p.hand.is_empty()
        blue_refresh = g.players[PID.BLUE].refresh
        assert c1 in blue_refresh.cards
        assert c2 in blue_refresh.cards

    def test_mix_discard_and_refresh(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        c1, c2, c3 = food(1), food(2), food(3)
        p.hand.slot(c1, c2, c3)  # hand order: [c3, c2, c1]

        run(g, _dump(PID.RED), interp(TextOption("Discard"), TextOption("Refresh"), TextOption("Discard")))

        assert c3 in g.players[PID.BLUE].discard.cards
        assert c2 in g.players[PID.BLUE].refresh.cards
        assert c1 in g.players[PID.BLUE].discard.cards

    def test_elusive_auto_refreshes_without_prompt(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        elusive = Card("elu", "Elusive", "", 1, (CardType.FOOD,), True, False)
        normal = food(2)
        p.hand.slot(elusive, normal)  # hand order: [normal, elusive]

        run(g, _dump(PID.RED), interp(TextOption("Discard")))

        assert p.hand.is_empty()
        assert elusive in g.players[PID.BLUE].refresh.cards
        assert normal in g.players[PID.BLUE].discard.cards

    def test_empty_hand_is_noop(self):
        g = initial_game(seed=42)
        run(g, _dump(PID.RED), interp())
        assert g.players[PID.RED].hand.is_empty()


# ---------- _manipulate ----------

class TestManipulate:
    """_manipulate: swap loop + optional force."""

    def test_done_immediately_no_swap(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        mf1, mf2 = food(1), food(2)
        h1 = food(3)
        p.sidebar.slot(mf1, mf2)
        p.hand.slot(h1)

        forcing: dict = {'card': None}
        run(g, _manipulate(PID.RED, forcing), interp(TextOption("Done"), TextOption("Don't force")))

        assert mf1 in p.sidebar.cards
        assert mf2 in p.sidebar.cards
        assert h1 in p.hand.cards
        assert forcing['card'] is None

    def test_swap_one_card(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        mf1 = food(1)
        h1 = food(9)
        p.sidebar.slot(mf1)
        p.hand.slot(h1)

        forcing: dict = {'card': None}
        run(g, _manipulate(PID.RED, forcing), interp(CardOption(mf1), CardOption(h1), TextOption("Done"), TextOption("Don't force")))

        assert h1 in p.sidebar.cards
        assert mf1 in p.hand.cards

    def test_force_discards_equipment_and_picks_card(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        mf1, mf2 = food(1), food(2)
        h1 = food(3)
        p.sidebar.slot(mf1, mf2)
        p.hand.slot(h1)
        equip = p.equipment.cards[0]  # role card from setup

        forcing: dict = {'card': None}
        # Sequence: Done (skip swap), equip (force), mf1 (which mf card to send)
        run(g, _manipulate(PID.RED, forcing),
            interp(TextOption("Done"), CardOption(equip), CardOption(mf1)))

        assert forcing['card'] is mf1
        assert equip in p.discard.cards
        assert equip not in p.equipment.cards

    def test_force_records_card_choice_distinct_from_other(self):
        """Kills the mutant where the card-choice prompt response is ignored.

        The manipulator picks mf2, not mf1; forcing['card'] must reflect that.
        """
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)
        equip = p.equipment.cards[0]

        forcing: dict = {'card': None}
        run(g, _manipulate(PID.RED, forcing),
            interp(TextOption("Done"), CardOption(equip), CardOption(mf2)))

        assert forcing['card'] is mf2
        assert forcing['card'] is not mf1

    def test_force_with_second_equipment_discards_correct_one(self):
        """Kills mutant: equipment_cards[choice-1] -> equipment_cards[choice-2].

        With 2 equipment cards and choice=2, choice-1=1 (correct second card)
        vs choice-2=0 (wrong first card).
        """
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        mf1 = food(1)
        h1 = food(2)
        p.sidebar.slot(mf1)
        p.hand.slot(h1)

        extra_equip = Card("shield", "Shield", "", None, (CardType.EQUIPMENT,), False, False)
        p.equipment.slot(extra_equip)
        role_card = [c for c in p.equipment.cards if c is not extra_equip][0]

        forcing: dict = {'card': None}
        # Done (skip swap), role_card (force via that equip), mf1 (only sidebar card)
        run(g, _manipulate(PID.RED, forcing),
            interp(TextOption("Done"), CardOption(role_card), CardOption(mf1)))

        assert forcing['card'] is mf1
        assert role_card in p.discard.cards
        assert extra_equip in p.equipment.cards  # first one NOT discarded


# ---------- _post_manipulation ----------

class TestPostManipulation:

    def test_clears_sidebar_and_fills_open_action_slots(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)

        open_count = sum(1 for s in other_p.action_field.slots_in_fill_order() if s.is_empty())

        run(g, _post_manipulation(PID.RED, None), interp())

        assert p.sidebar.is_empty()
        filled = [s for s in other_p.action_field.slots_in_fill_order() if not s.is_empty()]
        assert len(filled) == open_count

    def test_post_manipulate_distribution(self):
        """After PostManipulate alone (no subsequent action-field fills), the
        chosen card sits at opponent deck-top, the other two are in opponent's
        refresh, and sidebar is empty. The third card never visits sidebar."""
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]
        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)

        third_before = other_p.deck.cards[0]
        refresh_before = list(other_p.refresh.cards)

        run(g, do(PostManipulate(PID.RED, None, "test")), interp())

        assert p.sidebar.is_empty()
        chosen_dest = other_p.deck.cards[0]
        all_three = {mf1, mf2, third_before}
        assert chosen_dest in all_three
        new_refresh = set(other_p.refresh.cards) - set(refresh_before)
        assert len(new_refresh) == 2
        assert new_refresh == all_three - {chosen_dest}

    def test_force_routes_chosen_card_to_deck_top_then_action_field(self):
        """When forcing, the chosen card must end up at opponent's deck-top
        and be the first one drawn into the opponent's action field."""
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)

        # Drain action field so the first action-field draw is the chosen card.
        for slot in other_p.action_field.slots_in_fill_order():
            for c in list(slot.cards):
                slot.deslot(c)

        run(g, _post_manipulation(PID.RED, mf1), interp())

        # The first action-field slot in fill order must contain mf1.
        fill_order = other_p.action_field.slots_in_fill_order()
        first = fill_order[0]
        assert mf1 in first.cards

    def test_force_other_card_goes_to_action_field(self):
        """Kills mutant where forced_card is ignored. Picking mf2 must put mf2
        (not mf1) into opponent's first action slot."""
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        other_p = g.players[PID.BLUE]

        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)
        for slot in other_p.action_field.slots_in_fill_order():
            for c in list(slot.cards):
                slot.deslot(c)

        run(g, _post_manipulation(PID.RED, mf2), interp())

        first = other_p.action_field.slots_in_fill_order()[0]
        assert mf2 in first.cards
        assert mf1 not in first.cards

    def test_post_manipulated_event_emitted_with_forced_index(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)
        # mf1 is at sidebar index 1, mf2 at index 0 (slot prepends)
        idx_of_mf1 = p.sidebar.cards.index(mf1)

        g.drain_events()  # discard prior events
        run(g, _post_manipulation(PID.RED, mf1), interp())

        events = [e for e in g.drain_events() if isinstance(e, PostManipulated)]
        assert len(events) == 1
        assert events[0].manipulator == PID.RED
        assert events[0].forced == idx_of_mf1

    def test_post_manipulated_event_no_forced_when_random(self):
        g = initial_game(seed=42)
        p = g.players[PID.RED]
        mf1, mf2 = food(1), food(2)
        p.sidebar.slot(mf1, mf2)

        g.drain_events()
        run(g, _post_manipulation(PID.RED, None), interp())

        events = [e for e in g.drain_events() if isinstance(e, PostManipulated)]
        assert len(events) == 1
        assert events[0].manipulator == PID.RED
        assert events[0].forced is None


# ---------- integration ----------

class TestManipulationPhaseIntegration:

    def test_manipulate_with_force_reaches_post_manipulation(self):
        """Kills mutant: forcing['card'] -> None in manipulation_phase.

        With forcing, the manipulator picks an mf card before the third card
        is drawn. The PostManipulated event must carry a non-null `forced`
        index reflecting that choice; with the mutant, forced_card is dropped
        and the event's `forced` is None.
        """
        g = initial_game(seed=42)
        red = g.players[PID.RED]
        blue = g.players[PID.BLUE]

        mf1 = food(1)
        h1 = food(2)
        red.sidebar.slot(mf1)
        red.hand.slot(h1)

        # Drain blue's action field so the first deal lands the rigged card.
        for slot in blue.action_field.slots_in_fill_order():
            for c in list(slot.cards):
                slot.deslot(c)

        from phase.manipulation import manipulation_phase
        from interact.player import ScriptedPlayer
        from interact.interpret import AggregateInterpreter

        equip = red.equipment.cards[0]
        red_script = ScriptedPlayer([TextOption("Manipulate"), TextOption("Done"), CardOption(equip), CardOption(mf1)])
        blue_script = ScriptedPlayer([TextOption("Dump")])
        run(g, manipulation_phase(),
            AggregateInterpreter(red_script, blue_script))

        assert len(red.equipment.cards) == 0

        first_slot = blue.action_field.slots_in_fill_order()[0]
        assert mf1 in first_slot.cards, (
            "Forced card mf1 should land in blue's first action slot."
        )

        # RED's PostManipulated event must report a non-null forced index.
        red_pm = [e for e in g._event_log
                  if isinstance(e, PostManipulated) and e.manipulator == PID.RED]
        assert len(red_pm) == 1
        assert red_pm[0].forced is not None, (
            "RED forced; PostManipulated.forced must be a sidebar index, not None."
        )

        assert len(red_script.script) == 0, (
            f"RED interpreter has {len(red_script.script)} unconsumed choice(s). "
            f"Forcing prompt sequence was off."
        )

    def test_both_dump_empty_hands(self):
        """Both players dump with empty hands; post-manipulation runs cleanly.

        With the new design, each post-manipulation fills ALL open opponent
        action slots from opponent's own deck (PostManipulate is net-zero on
        deck count when sidebar is empty)."""
        g = initial_game(seed=42)
        initial_red = len(g.players[PID.RED].deck.cards)
        initial_blue = len(g.players[PID.BLUE].deck.cards)

        from phase.manipulation import manipulation_phase
        run(g, manipulation_phase(), interp(TextOption("Dump"), blue=[TextOption("Dump")]))

        # Each opp _post_manipulation drains 4 from this player's deck into
        # this player's action field (PostManipulate net-zero on deck).
        assert len(g.players[PID.RED].deck.cards) == initial_red - 4
        assert len(g.players[PID.BLUE].deck.cards) == initial_blue - 4

        for pid in [PID.RED, PID.BLUE]:
            af = g.players[pid].action_field
            total = sum(len(s.cards) for s in af.slots_in_fill_order())
            assert total == 4

        assert g.players[PID.RED].sidebar.is_empty()
        assert g.players[PID.BLUE].sidebar.is_empty()
