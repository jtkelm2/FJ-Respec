"""
Integration tests for networking layer.

Tests AsyncAggregateInterpreter, state pushing, and serialization
against real game states — not spec-level unit tests.
"""

import json

from core.type import (
    PID, PromptHalf, PlayerView,
    GameResult, Outcome, Ask, AskBoth, AskEither,
    compute_player_view, TextOption,
)
from interact.player import ScriptedPlayer, Player
from interact.interpret import AsyncAggregateInterpreter, ViewPushingInterpreter
from interact.serial import Accumulator
from phase.setup import create_initial_state


def _make_interp(g, red, blue):
    players: dict[PID, Player] = {PID.RED: red, PID.BLUE: blue}
    return ViewPushingInterpreter(g, players, AsyncAggregateInterpreter(red, blue))


# ── Helpers ───────────────────────────────────────────────────

class RecordingPlayer(ScriptedPlayer):
    """ScriptedPlayer that also records push_state calls."""
    def __init__(self, script):
        super().__init__(script)
        self.states: list[PlayerView] = []
        self.notifications: list[str] = []
        self.closed = False

    def push_state(self, view: PlayerView) -> None:
        self.states.append(view)

    def notify(self, text: str) -> None:
        self.notifications.append(text)

    def close(self) -> None:
        self.closed = True


# ── Serialization ─────────────────────────────────────────────

class TestSerialization:

    def test_player_view_round_trips_through_json(self):
        """A PlayerView serialized via Serializer survives JSON round-trip."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view)

        raw = json.dumps(serialized)
        recovered = json.loads(raw)
        assert recovered == serialized

    def test_all_enum_fields_become_strings(self):
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view)

        assert isinstance(serialized["priority"], str)
        assert serialized["priority"] in ("RED", "BLUE")
        assert all(isinstance(uid, int) for uid in serialized["hand"])

    def test_game_result_serializes(self):
        g = create_initial_state(seed=42)
        g.game_result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view)

        assert serialized["game_result"] is not None
        assert serialized["game_result"]["outcome"] == "GOOD_KILLED_EVIL"
        assert "RED" in serialized["game_result"]["winners"]

    def test_round_trip(self):
        """serialize then deserialize produces an equal PlayerView."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        deser = acc.deserializer()
        view = compute_player_view(g, PID.RED)
        assert deser.player_view(ser.player_view(view)) == view

    def test_round_trip_with_game_result(self):
        g = create_initial_state(seed=42)
        g.game_result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)
        acc = Accumulator(g)
        ser = acc.serializer()
        deser = acc.deserializer()
        view = compute_player_view(g, PID.RED)
        assert deser.player_view(ser.player_view(view)) == view


# ── AsyncAggregateInterpreter ────────────────────────────────

class TestAsyncAggregateInterpreter:

    def test_ask_single_player(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([TextOption("B")])
        blue = RecordingPlayer([])
        interp = _make_interp(g, red, blue)

        prompt = Ask(PID.RED, "Pick one", [TextOption("A"), TextOption("B")])
        response = interp.interpret(prompt)

        assert response == {PID.RED: TextOption("B")}

    def test_ask_both(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([TextOption("X")])
        blue = RecordingPlayer([TextOption("Y")])
        interp = _make_interp(g, red, blue)

        prompt = AskBoth({
            PID.RED: PromptHalf("Red?", [TextOption("X"), TextOption("Y")]),
            PID.BLUE: PromptHalf("Blue?", [TextOption("X"), TextOption("Y")]),
        })
        response = interp.interpret(prompt)

        assert response[PID.RED] == TextOption("X")
        assert response[PID.BLUE] == TextOption("Y")

    def test_ask_either_multi(self):
        """AskEither with two players returns whichever responds first."""
        g = create_initial_state(seed=42)
        red = RecordingPlayer([TextOption("A")])
        blue = RecordingPlayer([TextOption("C")])
        interp = _make_interp(g, red, blue)

        prompt = AskEither({
            PID.RED: PromptHalf("Red?", [TextOption("A")]),
            PID.BLUE: PromptHalf("Blue?", [TextOption("B"), TextOption("C")]),
        })
        response = interp.interpret(prompt)

        assert len(response) == 1
        pid = next(iter(response))
        assert pid in (PID.RED, PID.BLUE)

    def test_state_pushed_on_first_interpret(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([TextOption("ok")])
        blue = RecordingPlayer([])
        interp = _make_interp(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red.states) == 1
        assert len(blue.states) == 1

    def test_no_push_when_view_unchanged(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([TextOption("ok"), TextOption("ok")])
        blue = RecordingPlayer([])
        interp = _make_interp(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))
        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red.states) == 1
        assert len(blue.states) == 1

    def test_push_after_state_change(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([TextOption("ok"), TextOption("ok")])
        blue = RecordingPlayer([])
        interp = _make_interp(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        g.players[PID.RED].hp -= 5

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red.states) == 2
        assert red.states[0].hp != red.states[1].hp


# ── PlayerView fog of war ─────────────────────────────────────

class TestPlayerViewFogOfWar:

    def test_opponent_hp_hidden(self):
        g = create_initial_state(seed=42)
        g.players[PID.BLUE].hp = 7
        view = compute_player_view(g, PID.RED)

        assert view.hp == g.players[PID.RED].hp

    def test_own_hand_visible(self):
        g = create_initial_state(seed=42)
        view = compute_player_view(g, PID.RED)
        assert len(view.hand) == len(g.players[PID.RED].hand.cards)

    def test_opponent_hidden_slots_are_counts(self):
        from cards import enemy
        g = create_initial_state(seed=42)
        e = enemy(3)
        g.players[PID.BLUE].action_field.top_hidden.slot(e)

        view = compute_player_view(g, PID.RED)

        assert view.opp_action_field_top_hidden_count == 1
        assert isinstance(view.opp_action_field_top_distant, list)
