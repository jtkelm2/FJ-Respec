"""
Integration tests for networking layer.

Tests AsyncAggregateInterpreter, state pushing, and serialization
against real game states — not spec-level unit tests.
"""

import json
from dataclasses import asdict

from core.type import (
    PID, PKind, PromptHalf, PlayerView, CardView, CardType,
    GameResult, Outcome, Ask, AskBoth, AskEither,
    compute_player_view,
)
from interact.player import ScriptedInterpreter, _serialize_view, _GameEncoder
from interact.interpret import AsyncAggregateInterpreter
from interact.client import deserialize_view
from phase.setup import create_initial_state


# ── Helpers ───────────────────────────────────────────────────

class RecordingPlayer(ScriptedInterpreter):
    """ScriptedInterpreter that also records push_state calls."""
    def __init__(self, script):
        super().__init__(list(script))
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
        """A PlayerView from a real game state survives JSON serialization."""
        g = create_initial_state(seed=42)
        view = compute_player_view(g, PID.RED)
        serialized = _serialize_view(view)

        # Must be a plain dict (no dataclass instances, no enums)
        raw = json.dumps(serialized)
        recovered = json.loads(raw)
        assert recovered == serialized

    def test_all_enum_fields_become_strings(self):
        g = create_initial_state(seed=42)
        view = compute_player_view(g, PID.RED)
        serialized = _serialize_view(view)

        assert isinstance(serialized["priority"], str)
        assert serialized["priority"] in ("RED", "BLUE")
        for cv in serialized["hand"]:
            for t in cv["types"]:
                assert isinstance(t, str)

    def test_game_result_serializes(self):
        g = create_initial_state(seed=42)
        g.game_result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)
        view = compute_player_view(g, PID.RED)
        serialized = _serialize_view(view)

        assert serialized["game_result"] is not None
        assert serialized["game_result"]["outcome"] == "GOOD_KILLED_EVIL"
        assert "RED" in serialized["game_result"]["winners"]

    def test_round_trip(self):
        """serialize then deserialize produces an equal PlayerView."""
        g = create_initial_state(seed=42)
        view = compute_player_view(g, PID.RED)
        assert deserialize_view(_serialize_view(view)) == view

    def test_round_trip_with_game_result(self):
        g = create_initial_state(seed=42)
        g.game_result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)
        view = compute_player_view(g, PID.RED)
        assert deserialize_view(_serialize_view(view)) == view


# ── AsyncAggregateInterpreter ────────────────────────────────

class TestAsyncAggregateInterpreter:

    def test_ask_single_player(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([1])
        blue = RecordingPlayer([])
        interp = AsyncAggregateInterpreter(g, red, blue)

        prompt = Ask(PID.RED, "Pick one", ["A", "B"])
        response = interp.interpret(prompt)

        assert response == {PID.RED: 1}

    def test_ask_both(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([0])
        blue = RecordingPlayer([1])
        interp = AsyncAggregateInterpreter(g, red, blue)

        prompt = AskBoth({
            PID.RED: PromptHalf("Red?", ["X", "Y"]),
            PID.BLUE: PromptHalf("Blue?", ["X", "Y"]),
        })
        response = interp.interpret(prompt)

        assert response[PID.RED] == 0
        assert response[PID.BLUE] == 1

    def test_ask_either_multi(self):
        """AskEither with two players returns whichever responds first."""
        g = create_initial_state(seed=42)
        red = RecordingPlayer([0])
        blue = RecordingPlayer([1])
        interp = AsyncAggregateInterpreter(g, red, blue)

        prompt = AskEither({
            PID.RED: PromptHalf("Red?", ["A"]),
            PID.BLUE: PromptHalf("Blue?", ["B", "C"]),
        })
        response = interp.interpret(prompt)

        # Exactly one player answered
        assert len(response) == 1
        pid = next(iter(response))
        assert pid in (PID.RED, PID.BLUE)

    def test_state_pushed_on_first_interpret(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([0])
        blue = RecordingPlayer([])
        interp = AsyncAggregateInterpreter(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", ["ok"]))

        # Both players should have received a state push
        assert len(red.states) == 1
        assert len(blue.states) == 1

    def test_no_push_when_view_unchanged(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([0, 0])
        blue = RecordingPlayer([])
        interp = AsyncAggregateInterpreter(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", ["ok"]))
        interp.interpret(Ask(PID.RED, "?", ["ok"]))

        # Second call: game state didn't change, so no second push
        assert len(red.states) == 1
        assert len(blue.states) == 1

    def test_push_after_state_change(self):
        g = create_initial_state(seed=42)
        red = RecordingPlayer([0, 0])
        blue = RecordingPlayer([])
        interp = AsyncAggregateInterpreter(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", ["ok"]))

        # Mutate game state
        g.players[PID.RED].hp -= 5

        interp.interpret(Ask(PID.RED, "?", ["ok"]))

        # Red's view changed (hp), so red gets a second push
        assert len(red.states) == 2
        assert red.states[0].hp != red.states[1].hp


# ── PlayerView fog of war ─────────────────────────────────────

class TestPlayerViewFogOfWar:

    def test_opponent_hp_hidden(self):
        g = create_initial_state(seed=42)
        g.players[PID.BLUE].hp = 7
        view = compute_player_view(g, PID.RED)

        # Own HP visible
        assert view.hp == g.players[PID.RED].hp
        # No opponent HP field that reveals the value
        assert not hasattr(view, "opp_hp") or view.opp_hp is None

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
        # Distant slots are card views, not counts
        assert isinstance(view.opp_action_field_top_distant, list)
