"""Tests for the event log system: generation, draining, fog-of-war filtering."""

import random
from core.type import (
    PID, GameState, PlayerState, Slot, WeaponSlot, ActionField, Phase,
    Card, CardType, GameResult, Outcome,
    CardMoved, HPChanged, SlotShuffled, PlayerDied, PhaseChanged, GameEnded,
)
from core.engine import do
from interact.interpret import run, AggregateInterpreter
from interact.serial import Accumulator
from interact.player import ScriptedPlayer
from cards import food, weapon, enemy
from helpers import minimal_game, interp


class TestCardMovedEvents:

    def test_slot_card_emits_card_moved(self):
        from core.type import SlotCard
        g = minimal_game()
        c = food(3)
        src = g.players[PID.RED].hand
        dest = g.players[PID.RED].discard
        src.slot(c)

        run(g, do(SlotCard(c, dest, "test")), interp())

        events = g.drain_events()
        assert len(events) == 1
        assert isinstance(events[0], CardMoved)
        assert events[0].card is c
        assert events[0].source is src
        assert events[0].dest is dest

    def test_slot2slot_emits_card_moved(self):
        from core.type import Slot2Slot
        g = minimal_game()
        c = food(5)
        src = g.players[PID.RED].deck
        dest = g.players[PID.RED].hand
        src.slot(c)

        run(g, do(Slot2Slot(src, dest, "test")), interp())

        events = g.drain_events()
        moved = [e for e in events if isinstance(e, CardMoved)]
        assert len(moved) == 1
        assert moved[0].card is c
        assert moved[0].source is src
        assert moved[0].dest is dest

    def test_slot2slot_empty_source_no_event(self):
        from core.type import Slot2Slot
        g = minimal_game()
        src = Slot("empty")
        dest = Slot("dest")

        run(g, do(Slot2Slot(src, dest, "test")), interp())

        events = g.drain_events()
        assert not any(isinstance(e, CardMoved) for e in events)

    def test_slot2slot_all_emits_per_card(self):
        from core.type import Slot2SlotAll
        g = minimal_game()
        c1, c2, c3 = food(1), food(2), food(3)
        src = g.players[PID.RED].refresh
        dest = g.players[PID.RED].deck
        src.slot(c1, c2, c3)

        run(g, do(Slot2SlotAll(src, dest, "test")), interp())

        events = g.drain_events()
        moved = [e for e in events if isinstance(e, CardMoved)]
        assert len(moved) == 3
        assert all(m.source is src and m.dest is dest for m in moved)
        moved_cards = {m.card for m in moved}
        assert moved_cards == {c1, c2, c3}

    def test_discard_emits_card_moved_to_discard(self):
        from core.type import Discard
        g = minimal_game()
        c = food(3)
        g.players[PID.RED].hand.slot(c)

        run(g, do(Discard(PID.RED, c, "test")), interp())

        events = g.drain_events()
        moved = [e for e in events if isinstance(e, CardMoved)]
        assert len(moved) == 1
        assert moved[0].dest is g.players[PID.RED].discard

    def test_draw_emits_card_moved(self):
        from core.type import Draw
        g = minimal_game()
        c = food(7)
        g.players[PID.BLUE].deck.slot(c)

        run(g, do(Draw(PID.RED)), interp())

        events = g.drain_events()
        moved = [e for e in events if isinstance(e, CardMoved)]
        assert len(moved) == 1
        assert moved[0].card is c
        assert moved[0].dest is g.players[PID.RED].hand


class TestHPEvents:

    def test_damage_emits_hp_changed(self):
        from core.type import Damage
        g = minimal_game()

        run(g, do(Damage(PID.RED, 5, "test")), interp())

        events = g.drain_events()
        hp = [e for e in events if isinstance(e, HPChanged)]
        assert len(hp) == 1
        assert hp[0].target == PID.RED
        assert hp[0].old_hp == 20
        assert hp[0].new_hp == 15

    def test_lethal_damage_emits_hp_and_death(self):
        from core.type import Damage
        g = minimal_game()

        run(g, do(Damage(PID.RED, 25, "test")), interp())

        events = g.drain_events()
        hp = [e for e in events if isinstance(e, HPChanged)]
        died = [e for e in events if isinstance(e, PlayerDied)]
        assert len(hp) == 1
        assert hp[0].new_hp <= 0
        assert len(died) == 1
        assert died[0].target == PID.RED

    def test_hp_floor_clamping_reflected_in_event(self):
        from core.type import Damage
        g = minimal_game()
        g.players[PID.RED].hp_floor = 5

        run(g, do(Damage(PID.RED, 100, "test")), interp())

        events = g.drain_events()
        hp = [e for e in events if isinstance(e, HPChanged)]
        assert hp[0].new_hp == 5


class TestOtherEvents:

    def test_shuffle_emits_slot_shuffled(self):
        from core.type import Shuffle
        g = minimal_game()
        slot = g.players[PID.RED].deck
        slot.slot(food(1), food(2), food(3))

        run(g, do(Shuffle(slot, "test")), interp())

        events = g.drain_events()
        shuffled = [e for e in events if isinstance(e, SlotShuffled)]
        assert len(shuffled) == 1
        assert shuffled[0].slot is slot

    def test_start_phase_emits_phase_changed(self):
        from core.type import StartPhase
        g = minimal_game()

        run(g, do(StartPhase(Phase.ACTION, "test")), interp())

        events = g.drain_events()
        pc = [e for e in events if isinstance(e, PhaseChanged)]
        assert len(pc) == 1
        assert pc[0].phase == Phase.ACTION

    def test_end_phase_emits_phase_changed_none(self):
        from core.type import EndPhase
        g = minimal_game()

        run(g, do(EndPhase(Phase.ACTION)), interp())

        events = g.drain_events()
        pc = [e for e in events if isinstance(e, PhaseChanged)]
        assert len(pc) == 1
        assert pc[0].phase is None

    def test_game_over_emits_game_ended(self):
        from core.type import GameOver
        g = minimal_game()
        result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)

        run(g, do(GameOver(result, "test")), interp())

        events = g.drain_events()
        ended = [e for e in events if isinstance(e, GameEnded)]
        assert len(ended) == 1
        assert ended[0].result is result


class TestDrainEvents:

    def test_drain_clears_log(self):
        from core.type import Damage
        g = minimal_game()
        run(g, do(Damage(PID.RED, 1, "test")), interp())

        first = g.drain_events()
        assert len(first) > 0

        second = g.drain_events()
        assert len(second) == 0

    def test_new_events_after_drain(self):
        from core.type import Damage
        g = minimal_game()
        run(g, do(Damage(PID.RED, 1, "a")), interp())
        g.drain_events()

        run(g, do(Damage(PID.RED, 2, "b")), interp())
        events = g.drain_events()
        assert len(events) > 0


class TestFogOfWarFiltering:

    def _setup(self):
        from phase.setup import create_initial_state
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        return g, ser

    def test_own_hand_to_discard_visible_with_card(self):
        g, ser = self._setup()
        c = food(3)
        g.players[PID.RED].hand.slot(c)
        event = CardMoved(c, g.players[PID.RED].hand, g.players[PID.RED].discard)
        wire = ser._serialize_event(event, PID.RED)

        assert wire is not None
        assert wire["type"] == "card_moved"
        assert wire["card"] == c.name  # source is cards-visible

    def test_opponent_hidden_to_hidden_omitted(self):
        g, ser = self._setup()
        c = food(3)
        g.players[PID.BLUE].hand.slot(c)
        event = CardMoved(c, g.players[PID.BLUE].hand, g.players[PID.BLUE].refresh)
        wire = ser._serialize_event(event, PID.RED)

        assert wire is None  # both hidden from RED

    def test_deck_to_hand_count_only_no_card_name(self):
        g, ser = self._setup()
        c = g.players[PID.RED].deck.cards[0]
        event = CardMoved(c, g.players[PID.RED].deck, g.players[PID.RED].hand)
        wire = ser._serialize_event(event, PID.RED)

        assert wire is not None
        # source is count-only, dest is cards-visible → card name visible
        assert wire["card"] == c.name

    def test_opponent_deck_to_opponent_distant_visible(self):
        g, ser = self._setup()
        c = g.players[PID.BLUE].deck.cards[0]
        dest = g.players[PID.BLUE].action_field.top_distant
        event = CardMoved(c, g.players[PID.BLUE].deck, dest)
        wire = ser._serialize_event(event, PID.RED)

        assert wire is not None
        # dest is cards-visible to RED → card name shown
        assert wire["card"] == c.name

    def test_opponent_hp_change_hidden(self):
        g, ser = self._setup()
        event = HPChanged(PID.BLUE, 20, 15)
        wire = ser._serialize_event(event, PID.RED)
        assert wire is None

    def test_own_hp_change_visible(self):
        g, ser = self._setup()
        event = HPChanged(PID.RED, 20, 15)
        wire = ser._serialize_event(event, PID.RED)
        assert wire is not None
        assert wire["old"] == 20
        assert wire["new"] == 15

    def test_phase_changed_always_visible(self):
        g, ser = self._setup()
        event = PhaseChanged(Phase.ACTION)
        wire = ser._serialize_event(event, PID.RED)
        assert wire is not None
        assert wire["phase"] == "ACTION"

    def test_player_died_always_visible(self):
        g, ser = self._setup()
        event = PlayerDied(PID.BLUE)
        wire = ser._serialize_event(event, PID.RED)
        assert wire is not None
        assert wire["target"] == "BLUE"

    def test_shuffle_hidden_slot_omitted(self):
        g, ser = self._setup()
        event = SlotShuffled(g.players[PID.BLUE].refresh)
        wire = ser._serialize_event(event, PID.RED)
        assert wire is None

    def test_shuffle_own_deck_visible(self):
        g, ser = self._setup()
        event = SlotShuffled(g.players[PID.RED].deck)
        wire = ser._serialize_event(event, PID.RED)
        assert wire is not None
