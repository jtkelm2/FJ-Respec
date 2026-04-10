"""
Integration tests for networking layer.

Tests AsyncAggregateInterpreter, state pushing, and serialization
against real game states — not spec-level unit tests.
"""

import json

from core.type import (
    PID, PromptHalf, PlayerView,
    GameResult, Outcome, Ask, AskBoth, AskEither,
    compute_player_view, TextOption, CardOption,
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
        serialized = ser.player_view(view, PID.RED)

        raw = json.dumps(serialized)
        recovered = json.loads(raw)
        assert recovered == serialized

    def test_all_enum_fields_become_strings(self):
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert isinstance(serialized["priority"], str)
        assert serialized["priority"] in ("RED", "BLUE")

    def test_game_result_serializes(self):
        g = create_initial_state(seed=42)
        g.game_result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert serialized["game_result"] is not None
        assert serialized["game_result"]["outcome"] == "GOOD_KILLED_EVIL"
        assert "RED" in serialized["game_result"]["winners"]

    def test_slots_keyed_by_name(self):
        """State slots dict is keyed by slot names."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert isinstance(serialized["slots"], dict)
        assert "red_hand" in serialized["slots"]
        assert "blue_deck" in serialized["slots"]
        assert "guard_deck" in serialized["slots"]

    def test_card_names_reference_catalog(self):
        """Every card name in a state view appears in the catalog."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        catalog = acc.catalog(PID.RED)
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        catalog_names = set(catalog["cards"].keys())
        for slot_val in serialized["slots"].values():
            if isinstance(slot_val, list):
                for name in slot_val:
                    assert name in catalog_names

    def test_catalog_slots_organized_by_owner_and_role(self):
        """Catalog slots are nested: {owner: {role: name}}."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        catalog = acc.catalog(PID.RED)

        assert "self" in catalog["slots"]
        assert "opponent" in catalog["slots"]
        assert "shared" in catalog["slots"]
        assert catalog["slots"]["self"]["hand"] == "red_hand"
        assert catalog["slots"]["self"]["deck"] == "red_deck"
        assert catalog["slots"]["self"]["equipment"] == "red_equipment"
        assert catalog["slots"]["shared"]["guard_deck"] == "guard_deck"

    def test_catalog_owner_labels_relative_to_pid(self):
        """Catalog labels slots as self/opponent/shared relative to receiving player."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        red_catalog = acc.catalog(PID.RED)
        blue_catalog = acc.catalog(PID.BLUE)

        # RED's "self" slots are BLUE's "opponent" slots (same names)
        assert set(red_catalog["slots"]["self"].values()) == \
               set(blue_catalog["slots"]["opponent"].values())
        # And vice versa
        assert set(red_catalog["slots"]["opponent"].values()) == \
               set(blue_catalog["slots"]["self"].values())

    def test_identical_cards_share_wire_name(self):
        """Two copies of the same card (e.g. enemy_3) share the same name on the wire."""
        from cards import enemy
        e1 = enemy(3)
        e2 = enemy(3)
        assert e1.name == e2.name == "enemy_3"

    def test_card_option_uses_slot_name_and_index(self):
        """CardOption serialization uses slot name and index."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()

        hand = g.players[PID.RED].hand
        top = g.players[PID.RED].deck.draw()
        hand.slot(top)

        opt = CardOption(top)
        serialized = ser.option(opt)

        assert serialized["type"] == "card"
        assert serialized["slot"] == "red_hand"
        assert serialized["index"] == hand.cards.index(top)

    def test_weapon_slots_in_catalog(self):
        """Weapon slots are nested by owner and role."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        catalog = acc.catalog(PID.RED)

        assert "self" in catalog["weapon_slots"]
        assert "ws_0" in catalog["weapon_slots"]["self"]

    def test_weapons_in_state(self):
        """Weapons in state carry name, card, sharpness, kills."""
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert "weapons" in serialized
        for w in serialized["weapons"]:
            assert "name" in w
            assert "sharpness" in w
            assert "kills" in w
            assert "card" in w


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
