"""
Slot system: card-slot bookkeeping and conservation invariants.

Every card knows its current slot (card.slot). Every slot move must
maintain referential integrity and conserve total card count.
"""

import pytest
from core.type import Slot, Card, CardType
from cards import food, weapon, enemy


def _card(name="c"):
    return Card(name, name, "", 1, (CardType.FOOD,), False, False)


# ---------- card.slot bookkeeping ----------

class TestSlotBookkeeping:
    """card.slot reference tracks current location at all times."""

    def test_new_card_has_no_slot(self):
        assert _card().slot is None

    def test_slot_sets_card_reference(self):
        s = Slot("t")
        c = _card()
        s.slot(c)
        assert c.slot is s

    def test_deslot_clears_card_reference(self):
        s = Slot("t")
        c = _card()
        s.slot(c)
        s.deslot(c)
        assert c.slot is None

    def test_draw_clears_card_reference(self):
        s = Slot("t")
        c = _card()
        s.slot(c)
        drawn = s.draw()
        assert drawn is c
        assert c.slot is None

    def test_slotting_into_new_slot_auto_deslots_from_old(self):
        s1 = Slot("t")
        s2 = Slot("t")
        c = _card()
        s1.slot(c)
        s2.slot(c)
        assert c not in s1.cards
        assert c in s2.cards
        assert c.slot is s2


# ---------- ordering ----------

class TestSlotOrdering:
    """Slot is LIFO: slot() inserts at front, draw() pops from front."""

    def test_slot_inserts_at_front(self):
        s = Slot("t")
        a, b, c = _card("a"), _card("b"), _card("c")
        s.slot(a)
        s.slot(b)
        s.slot(c)
        assert s.cards[0] is c
        assert s.cards[1] is b
        assert s.cards[2] is a

    def test_draw_returns_front_card(self):
        s = Slot("t")
        a, b = _card("a"), _card("b")
        s.slot(a)
        s.slot(b)
        assert s.draw() is b

    def test_multi_slot_reverses_argument_order(self):
        """slot(a, b, c) inserts sequentially, so cards end up [c, b, a]."""
        s = Slot("t")
        a, b, c = _card("a"), _card("b"), _card("c")
        s.slot(a, b, c)
        assert s.cards == [c, b, a]


# ---------- card conservation ----------

class TestCardConservation:
    """Cards are never created or destroyed by slot operations."""

    def test_move_via_draw_conserves_count(self):
        s1, s2 = Slot("t"), Slot("t")
        cards = [_card(f"c{i}") for i in range(5)]
        s1.slot(*cards)

        for _ in range(3):
            s2.slot(s1.draw())

        assert len(s1.cards) + len(s2.cards) == 5

    def test_auto_deslot_does_not_duplicate(self):
        s1, s2 = Slot("t"), Slot("t")
        c = _card()
        s1.slot(c)
        s2.slot(c)
        assert len(s1.cards) + len(s2.cards) == 1

    def test_full_transfer_conserves_count(self):
        s1, s2 = Slot("t"), Slot("t")
        all_cards = [_card(f"c{i}") for i in range(10)]
        s1.slot(*all_cards)

        while not s1.is_empty():
            s2.slot(s1.draw())

        assert len(s2.cards) == 10
        assert s1.is_empty()


# ---------- edge cases & error paths ----------

class TestSlotEdgeCases:

    def test_empty_slot_is_empty(self):
        assert Slot("t").is_empty()

    def test_non_empty_slot_is_not_empty(self):
        assert not Slot("t", [_card()]).is_empty()

    def test_draw_last_card_makes_slot_empty(self):
        s = Slot("t", [_card()])
        s.draw()
        assert s.is_empty()

    def test_constructor_slots_all_cards(self):
        cards = [_card("a"), _card("b")]
        s = Slot("t", cards)
        assert len(s.cards) == 2
        for c in cards:
            assert c.slot is s

    def test_deslot_absent_card_raises(self):
        with pytest.raises(AssertionError):
            Slot("t").deslot(_card())

    def test_draw_from_empty_raises(self):
        with pytest.raises(AssertionError):
            Slot("t").draw()


# ---------- Card.is_type ----------

class TestCardIsType:

    def test_single_type_match(self):
        c = food(1)
        assert c.is_type(CardType.FOOD)
        assert not c.is_type(CardType.WEAPON)

    def test_multi_type_card(self):
        c = Card("hybrid", "Hybrid", "", 1,
                  (CardType.FOOD, CardType.WEAPON), False, False)
        assert c.is_type(CardType.FOOD)
        assert c.is_type(CardType.WEAPON)
        assert not c.is_type(CardType.ENEMY)
