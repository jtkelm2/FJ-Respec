"""
Integration tests for networking layer.

Tests AsyncAggregateInterpreter, state pushing, and serialization
against real game states — not spec-level unit tests.
"""

import json
from threading import Event

from core.type import (
    PID, PKind, PromptHalf,
    GameResult, Outcome, Ask, AskBoth, AskEither,
    compute_player_view, TextOption,
)
from interact.player import RemotePlayer, Connection
from interact.interpret import AsyncAggregateInterpreter
from interact.serial import Accumulator
from phase.setup import create_initial_state


# ── Helpers ───────────────────────────────────────────────────

class ScriptedConnection(Connection):
    """Connection that sends scripted responses when prompted.

    Outgoing messages (send) are recorded. Incoming messages (recv)
    block until a prompt is sent, then respond with the next scripted option.
    """
    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.sent: list[dict] = []
        self._prompt_ready = Event()

    def send(self, msg: dict) -> None:
        self.sent.append(msg)
        if msg.get("type") == "prompt":
            self._prompt_ready.set()

    def recv(self) -> dict:
        self._prompt_ready.wait()
        self._prompt_ready.clear()
        return self.script.pop(0)

    def close(self) -> None:
        pass

    @property
    def states(self) -> list[dict]:
        return [m["view"] for m in self.sent if m.get("type") == "state"]


def _make_players(g, red_options: list[TextOption], blue_options: list[TextOption]):
    """Build RemotePlayers with ScriptedConnections for testing."""
    acc = Accumulator(g)
    ser = acc.serializer()

    def _script(options):
        return [{"type": "response", "option": ser.option(o)} for o in options]

    red_conn = ScriptedConnection(_script(red_options))
    blue_conn = ScriptedConnection(_script(blue_options))
    red = RemotePlayer(red_conn, ser, "RED")
    blue = RemotePlayer(blue_conn, ser, "BLUE")
    return red, blue, red_conn, blue_conn


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
        red, blue, _, _ = _make_players(g, [TextOption("B")], [])
        interp = AsyncAggregateInterpreter(g, red, blue)

        prompt = Ask(PID.RED, "Pick one", [TextOption("A"), TextOption("B")])
        response = interp.interpret(prompt)

        assert response == {PID.RED: TextOption("B")}

    def test_ask_both(self):
        g = create_initial_state(seed=42)
        red, blue, _, _ = _make_players(g, [TextOption("X")], [TextOption("Y")])
        interp = AsyncAggregateInterpreter(g, red, blue)

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
        red, blue, _, _ = _make_players(g, [TextOption("A")], [TextOption("C")])
        interp = AsyncAggregateInterpreter(g, red, blue)

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
        red, blue, red_conn, blue_conn = _make_players(g, [TextOption("ok")], [])
        interp = AsyncAggregateInterpreter(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red_conn.states) >= 1
        assert len(blue_conn.states) >= 1

    def test_no_push_when_view_unchanged(self):
        g = create_initial_state(seed=42)
        red, blue, red_conn, blue_conn = _make_players(g, [TextOption("ok"), TextOption("ok")], [])
        interp = AsyncAggregateInterpreter(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))
        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red_conn.states) == 1
        assert len(blue_conn.states) == 1

    def test_push_after_state_change(self):
        g = create_initial_state(seed=42)
        red, blue, red_conn, _ = _make_players(g, [TextOption("ok"), TextOption("ok")], [])
        interp = AsyncAggregateInterpreter(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        g.players[PID.RED].hp -= 5

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red_conn.states) == 2


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
