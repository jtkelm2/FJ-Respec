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
from interact.player import ScriptedPlayer, Player, RemotePlayer, PidAssignment, Info
from interact.interpret import AsyncAggregateInterpreter, ViewPushingInterpreter
from interact.serial import Accumulator
from helpers import initial_game


class _FakeConnection:
    """Minimal Connection stand-in for wire-format tests: records sends, never receives."""
    def __init__(self):
        self.sent: list[dict] = []
        self._never_receive = __import__("threading").Event()

    def send(self, msg: dict) -> None:
        self.sent.append(msg)

    def recv(self) -> dict:
        # Block forever — tests don't exercise the receive path.
        self._never_receive.wait()
        raise RuntimeError("unreachable")  # pragma: no cover

    def close(self) -> None:
        pass


def _make_interp(g, red, blue):
    players: dict[PID, Player] = {PID.RED: red, PID.BLUE: blue}
    return ViewPushingInterpreter(g, players, AsyncAggregateInterpreter(red, blue))


# ── Helpers ───────────────────────────────────────────────────

class RecordingPlayer(ScriptedPlayer):
    """ScriptedPlayer that also records push_state calls."""
    def __init__(self, script):
        super().__init__(script)
        self.states: list[PlayerView] = []
        self.notifications: list = []
        self.closed = False

    def push_state(self, view: PlayerView, events: list | None = None) -> None:
        self.states.append(view)

    def notify(self, notification) -> None:
        self.notifications.append(notification)

    def close(self) -> None:
        self.closed = True


# ── Serialization ─────────────────────────────────────────────

class TestSerialization:

    def test_player_view_round_trips_through_json(self):
        """A PlayerView serialized via Serializer survives JSON round-trip."""
        g = initial_game(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        raw = json.dumps(serialized)
        recovered = json.loads(raw)
        assert recovered == serialized

    def test_all_enum_fields_become_strings(self):
        g = initial_game(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert isinstance(serialized["priority"], str)
        assert serialized["priority"] in ("RED", "BLUE")

    def test_game_result_serializes(self):
        g = initial_game(seed=42)
        g.game_result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert serialized["game_result"]["outcome"] == "GOOD_KILLED_EVIL"
        assert "RED" in serialized["game_result"]["winners"]

    def test_game_result_omitted_during_play(self):
        """game_result key is absent (not null) while the game is in progress."""
        g = initial_game(seed=42)
        assert g.game_result is None
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert "game_result" not in serialized

    def test_current_phase_omitted_when_no_phase(self):
        """current_phase key is absent (not null) between phases."""
        g = initial_game(seed=42)
        g.current_phase = None
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert "current_phase" not in serialized

    def test_card_level_omitted_when_not_applicable(self):
        """Cards without a level (e.g. role cards / equipment) omit the 'level' key."""
        g = initial_game(seed=42)
        catalog = Accumulator(g).catalog()
        # Role cards have no level concept — the key must be absent rather than null.
        leveled = [name for name, e in catalog["cards"].items() if "level" in e]
        unleveled = [name for name, e in catalog["cards"].items() if "level" not in e]
        # Sanity: both populations exist (mixed cards in a real game).
        assert leveled, "expected at least one card with a level"
        assert unleveled, "expected at least one card without a level"
        # No card carries level=None.
        for entry in catalog["cards"].values():
            assert entry.get("level") is not None or "level" not in entry

    def test_slots_keyed_by_name(self):
        """State slots dict is keyed by slot names."""
        g = initial_game(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        assert isinstance(serialized["slots"], dict)
        assert "red_hand" in serialized["slots"]
        # Opponent deck count IS visible
        assert "blue_deck" in serialized["slots"]
        assert isinstance(serialized["slots"]["blue_deck"], int)
        # Opponent distant action field IS visible
        assert "blue_action_field_top_distant" in serialized["slots"]
        assert "guard_deck" in serialized["slots"]

    def test_card_names_reference_catalog(self):
        """Every card name in a state view appears in the catalog."""
        g = initial_game(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        catalog = acc.catalog()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        catalog_names = set(catalog["cards"].keys())
        for slot_val in serialized["slots"].values():
            if isinstance(slot_val, list):
                for entry in slot_val:
                    assert entry["name"] in catalog_names

    def test_catalog_slots_keyed_by_wire_name(self):
        """Catalog slots are flat: {wire_name: {owner, role}} with absolute PIDs."""
        g = initial_game(seed=42)
        acc = Accumulator(g)
        catalog = acc.catalog()

        assert catalog["slots"]["red_hand"] == {"owner": "RED", "role": "hand"}
        assert catalog["slots"]["red_deck"] == {"owner": "RED", "role": "deck"}
        assert catalog["slots"]["red_equipment"] == {"owner": "RED", "role": "equipment"}
        assert catalog["slots"]["blue_hand"] == {"owner": "BLUE", "role": "hand"}
        # Unowned slots: 'owner' key is omitted entirely rather than null.
        assert catalog["slots"]["guard_deck"] == {"role": "guard_deck"}

    def test_catalog_is_identical_for_both_players(self):
        """The catalog no longer carries per-receiver perspective — it is a
        single shared vocabulary, identical for RED and BLUE clients."""
        g = initial_game(seed=42)
        acc = Accumulator(g)
        # No-arg call: catalog is symmetric.
        catalog_a = acc.catalog()
        catalog_b = acc.catalog()
        assert catalog_a == catalog_b
        # And every owner (when present) is an absolute PID name — never "self"/"opponent".
        # The owner key is omitted entirely for unowned slots.
        for info in catalog_a["slots"].values():
            assert info.get("owner") in ("RED", "BLUE", None)
        for info in catalog_a["weapon_slots"].values():
            assert info.get("owner") in ("RED", "BLUE", None)

    def test_identical_cards_share_wire_name(self):
        """Two copies of the same card (e.g. enemy_3) share the same name on the wire."""
        from cards import enemy
        e1 = enemy(3)
        e2 = enemy(3)
        assert e1.name == e2.name == "enemy_3"

    def test_card_option_uses_slot_name_and_index(self):
        """CardOption serialization uses slot name and index."""
        g = initial_game(seed=42)
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
        """Weapon slots are keyed by wire name with absolute PID owners."""
        g = initial_game(seed=42)
        acc = Accumulator(g)
        catalog = acc.catalog()

        assert "red_ws_0" in catalog["weapon_slots"]
        assert catalog["weapon_slots"]["red_ws_0"]["owner"] == "RED"
        assert catalog["weapon_slots"]["red_ws_0"]["role"] == "ws_0"
        assert catalog["weapon_slots"]["blue_ws_0"]["owner"] == "BLUE"

    def test_weapons_in_state(self):
        """Weapons in state carry name, card, sharpness, kills."""
        g = initial_game(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()
        view = compute_player_view(g, PID.RED)
        serialized = ser.player_view(view, PID.RED)

        # weapons field is gone — weapon holder + killstack live in slots
        assert "weapons" not in serialized
        assert "red_ws_0_weapon" in serialized["slots"]
        assert "red_ws_0_killstack" in serialized["slots"]
        assert isinstance(serialized["slots"]["red_ws_0_weapon"], list)
        assert isinstance(serialized["slots"]["red_ws_0_killstack"], list)

    def test_view_has_players_block_with_absolute_pids(self):
        """The view's per-player info lives in `players: {RED: {...}, BLUE: {...}}`,
        with the receiver's own info filled and the opponent's hidden as null."""
        g = initial_game(seed=42)
        g.players[PID.RED].hp = 17
        g.players[PID.BLUE].hp = 13
        acc = Accumulator(g)
        ser = acc.serializer()

        red_view = compute_player_view(g, PID.RED)
        red_ser = ser.player_view(red_view, PID.RED)

        # No top-level role/alignment/hp fields anymore.
        assert "role" not in red_ser
        assert "alignment" not in red_ser
        assert "hp" not in red_ser

        # Both PIDs are always present as keys.
        assert set(red_ser["players"].keys()) == {"RED", "BLUE"}

        # Own block carries real values.
        assert red_ser["players"]["RED"]["hp"] == 17

        # Opponent block has null role/alignment/hp (fog of war).
        assert red_ser["players"]["BLUE"]["hp"] is None
        assert red_ser["players"]["BLUE"]["role"] is None
        assert red_ser["players"]["BLUE"]["alignment"] is None

        # Symmetric for BLUE.
        blue_view = compute_player_view(g, PID.BLUE)
        blue_ser = ser.player_view(blue_view, PID.BLUE)
        assert blue_ser["players"]["BLUE"]["hp"] == 13
        assert blue_ser["players"]["RED"]["hp"] is None

    def test_pid_assignment_wire_format(self):
        """RemotePlayer.notify(PidAssignment(pid)) emits the documented wire form."""
        g = initial_game(seed=42)
        ser = Accumulator(g).serializer()
        conn = _FakeConnection()
        rp = RemotePlayer(conn, ser, PID.RED, "test")

        rp.notify(PidAssignment(PID.RED))
        rp.notify(PidAssignment(PID.BLUE))
        rp.notify(Info("hello"))

        # First two are pid_assignment notifies with absolute PID names.
        assert conn.sent[0] == {"type": "notify", "kind": "pid_assignment", "pid": "RED"}
        assert conn.sent[1] == {"type": "notify", "kind": "pid_assignment", "pid": "BLUE"}
        # Info notification continues to work.
        assert conn.sent[2] == {"type": "notify", "kind": "info", "text": "hello"}

    def test_hp_changed_event_carries_target(self):
        """hp_changed wire event names the player whose HP changed (own only)."""
        from core.type import HPChanged
        g = initial_game(seed=42)
        acc = Accumulator(g)
        ser = acc.serializer()

        # Own HP change — event is emitted with explicit target.
        own = ser.events([HPChanged(PID.RED, 20, 15)], PID.RED)
        assert own == [{"type": "hp_changed", "target": "RED", "old": 20, "new": 15}]

        # Opponent HP change — fog-of-war filtered out.
        opp = ser.events([HPChanged(PID.BLUE, 20, 15)], PID.RED)
        assert opp == []


# ── AsyncAggregateInterpreter ────────────────────────────────

class TestAsyncAggregateInterpreter:

    def test_ask_single_player(self):
        g = initial_game(seed=42)
        red = RecordingPlayer([TextOption("B")])
        blue = RecordingPlayer([])
        interp = _make_interp(g, red, blue)

        prompt = Ask(PID.RED, "Pick one", [TextOption("A"), TextOption("B")])
        response = interp.interpret(prompt)

        assert response == {PID.RED: TextOption("B")}

    def test_ask_both(self):
        g = initial_game(seed=42)
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
        g = initial_game(seed=42)
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
        g = initial_game(seed=42)
        red = RecordingPlayer([TextOption("ok")])
        blue = RecordingPlayer([])
        interp = _make_interp(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red.states) == 1
        assert len(blue.states) == 1

    def test_no_push_when_view_unchanged(self):
        g = initial_game(seed=42)
        red = RecordingPlayer([TextOption("ok"), TextOption("ok")])
        blue = RecordingPlayer([])
        interp = _make_interp(g, red, blue)

        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))
        interp.interpret(Ask(PID.RED, "?", [TextOption("ok")]))

        assert len(red.states) == 1
        assert len(blue.states) == 1

    def test_push_after_state_change(self):
        g = initial_game(seed=42)
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
        g = initial_game(seed=42)
        g.players[PID.BLUE].hp = 7
        view = compute_player_view(g, PID.RED)

        assert view.hp == g.players[PID.RED].hp

    def test_own_hand_visible(self):
        g = initial_game(seed=42)
        view = compute_player_view(g, PID.RED)
        assert len(view.hand) == len(g.players[PID.RED].hand.cards)

    def test_opponent_hidden_slots_not_in_view(self):
        """Opponent hidden slots, equipment, deck, refresh, discard are not exposed."""
        view = compute_player_view(initial_game(seed=42), PID.RED)
        assert not hasattr(view, "opp_action_field_top_hidden_count")
        assert not hasattr(view, "opp_equipment_count")
        # Opponent deck count IS visible
        assert isinstance(view.opp_deck_size, int)
        # Distant action field IS visible
        assert isinstance(view.opp_action_field_top_distant, list)
