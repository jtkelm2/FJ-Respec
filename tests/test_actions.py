"""
Action primitives and their compositions through do().

Draw -> EnsureDeck + Slot2Slot (from OTHER player's deck)
EnsureDeck -> ShuffleRefreshIntoDeck -> Death (if still empty)
Discard / Refresh -> SlotCard into the appropriate pile
"""

from core.type import (
    PID, Slot, Damage,
    Draw, EnsureDeck, SlotCard, Slot2Slot, Slot2SlotAll,
    FlipPriority, Refresh, Discard, Shuffle,
)
from core.engine import run, do
from helpers import interp
from cards import food, enemy
from phase.setup import create_initial_state


# ---------- Draw ----------

class TestDraw:
    """Draw(pid) draws from other(pid)'s deck into pid's hand."""

    def test_draw_takes_from_other_deck(self):
        g = create_initial_state(seed=42)
        blue_top = g.players[PID.BLUE].deck.cards[0]
        hand_before = len(g.players[PID.RED].hand.cards)

        run(g, do(Draw(PID.RED)), interp())

        assert blue_top in g.players[PID.RED].hand.cards
        assert len(g.players[PID.RED].hand.cards) == hand_before + 1

    def test_draw_does_not_touch_own_deck(self):
        g = create_initial_state(seed=42)
        red_deck_size = len(g.players[PID.RED].deck.cards)
        run(g, do(Draw(PID.RED)), interp())
        assert len(g.players[PID.RED].deck.cards) == red_deck_size


# ---------- EnsureDeck ----------

class TestEnsureDeck:

    def test_noop_when_deck_has_cards(self):
        g = create_initial_state(seed=42)
        deck_size = len(g.players[PID.RED].deck.cards)
        run(g, do(EnsureDeck(PID.RED)), interp())
        assert len(g.players[PID.RED].deck.cards) == deck_size

    def test_shuffles_refresh_into_deck(self):
        g = create_initial_state(seed=42)
        p = g.players[PID.RED]
        # Move all deck cards to refresh
        for c in list(p.deck.cards):
            p.refresh.slot(c)
        assert p.deck.is_empty()
        assert not p.refresh.is_empty()

        run(g, do(EnsureDeck(PID.RED)), interp())

        assert not p.deck.is_empty()
        assert p.refresh.is_empty()

    def test_kills_both_when_truly_empty(self):
        g = create_initial_state(seed=42)
        g.players[PID.RED].deck._cards.clear()
        g.players[PID.RED].refresh._cards.clear()

        run(g, do(EnsureDeck(PID.RED)), interp())

        assert g.players[PID.RED].is_dead
        assert g.players[PID.BLUE].is_dead


# ---------- SlotCard ----------

class TestSlotCard:

    def test_auto_moves_from_previous_slot(self):
        g = create_initial_state(seed=42)
        c = food(1)
        s1, s2 = Slot(), Slot()
        s1.slot(c)

        run(g, do(SlotCard(c, s2)), interp())

        assert c not in s1.cards
        assert c in s2.cards
        assert c.slot is s2


# ---------- Slot2Slot ----------

class TestSlot2Slot:

    def test_moves_exactly_one_card(self):
        g = create_initial_state(seed=42)
        s1, s2 = Slot(), Slot()
        s1.slot(food(1), food(2))

        run(g, do(Slot2Slot(s1, s2)), interp())

        assert len(s1.cards) == 1
        assert len(s2.cards) == 1

    def test_noop_from_empty_source(self):
        g = create_initial_state(seed=42)
        s1, s2 = Slot(), Slot()
        s2.slot(food(1))

        run(g, do(Slot2Slot(s1, s2)), interp())
        assert len(s2.cards) == 1


# ---------- Slot2SlotAll ----------

class TestSlot2SlotAll:

    def test_transfers_everything(self):
        g = create_initial_state(seed=42)
        s1, s2 = Slot(), Slot()
        s1.slot(*[food(i) for i in range(1, 6)])

        run(g, do(Slot2SlotAll(s1, s2)), interp())

        assert s1.is_empty()
        assert len(s2.cards) == 5

    def test_noop_from_empty(self):
        g = create_initial_state(seed=42)
        s1, s2 = Slot(), Slot()
        run(g, do(Slot2SlotAll(s1, s2)), interp())
        assert s1.is_empty()
        assert s2.is_empty()


# ---------- FlipPriority ----------

class TestFlipPriority:

    def test_toggles(self):
        g = create_initial_state(seed=42)
        original = g.priority
        run(g, do(FlipPriority()), interp())
        from core.type import other
        assert g.priority == other(original)

    def test_double_flip_restores(self):
        g = create_initial_state(seed=42)
        original = g.priority
        run(g, do(FlipPriority()), interp())
        run(g, do(FlipPriority()), interp())
        assert g.priority == original


# ---------- Refresh / Discard actions ----------

class TestRefreshAction:

    def test_moves_card_to_refresh_pile(self):
        g = create_initial_state(seed=42)
        c = food(5)
        g.players[PID.RED].hand.slot(c)

        run(g, do(Refresh(c, PID.RED)), interp())

        assert c in g.players[PID.RED].refresh.cards
        assert c not in g.players[PID.RED].hand.cards

    def test_refresh_to_other_player(self):
        g = create_initial_state(seed=42)
        c = food(5)
        g.players[PID.RED].hand.slot(c)

        run(g, do(Refresh(c, PID.BLUE)), interp())

        assert c in g.players[PID.BLUE].refresh.cards


class TestDiscardAction:

    def test_moves_card_to_discard_pile(self):
        g = create_initial_state(seed=42)
        c = food(3)
        g.players[PID.RED].hand.slot(c)

        run(g, do(Discard(PID.RED, c, "test")), interp())

        assert c in g.players[PID.RED].discard.cards
        assert c not in g.players[PID.RED].hand.cards
