"""
Tests for RevealedCardOption + PromptHalf.must_select.

Two intertwined features:

  - `RevealedCardOption(card)` identifies a card by template name only (no slot/index).
    Used when the card lives in a slot hidden from the recipient (opponent hand,
    own deck/refresh, etc.) where a location-anchored CardOption would dangle.
  - `PromptHalf.must_select: int = 1` lets a single prompt accept exactly N
    selections. Player.prompt returns a bare Option when N == 1, list[Option]
    when N >= 2.

Cards exercised end-to-end: Piñata Stick (weapon_3), Detective (good_role_8),
High Priestess (major_2).
"""

import pytest

from core.type import (
    PID, CardType, PromptHalf, PromptBuilder, Prompt, PKind,
    Option, TextOption, CardOption, RevealedCardOption, SlotOption,
    Resolve, Discard, Damage,
)
from core.engine import do
from interact.interpret import run
from interact.player import ScriptedPlayer
from interact.serial import Serializer, Accumulator
from helpers import interp, minimal_game, count_all_cards
from cards import (
    weapon_3, detective, the_high_priestess,
    food, food_3, food_7, enemy, weapon, weapon_1,
)


# --- Helpers -------------------------------------------------------------

def _serializer(g):
    return Accumulator(g).serializer()


# --- RevealedCardOption: factory + serialization -------------------------

class TestRevealedCardOption:

    def test_str_renders_display_name(self):
        c = food(5)
        assert str(RevealedCardOption(c)) == c.display_name

    def test_serializes_to_name_only(self):
        g = minimal_game()
        ser = _serializer(g)
        c = food(5)
        assert ser.option(RevealedCardOption(c)) == {"type": "revealed_card", "name": "food_5"}

    def test_serializes_without_counters_even_when_card_has_counters(self):
        g = minimal_game()
        ser = _serializer(g)
        c = food(5)
        c.counters = 7
        wire = ser.option(RevealedCardOption(c))
        assert "counters" not in wire
        assert wire["name"] == "food_5"

    def test_card_option_still_serializes_by_location(self):
        """Regression: existing CardOption shape unchanged."""
        g = minimal_game()
        c = food(3)
        g.players[PID.RED].hand.slot(c)
        ser = _serializer(g)
        assert ser.option(CardOption(c)) == {"type": "card", "slot": "red_hand", "index": 0}

    def test_revealed_card_option_does_not_require_a_slot(self):
        """RevealedCardOption works for cards whose .slot is None — the whole
        point is to identify by template name when location is unavailable."""
        g = minimal_game()
        ser = _serializer(g)
        c = food(5)
        c.slot = None  # explicit: card not in any slot
        # CardOption would assert here; RevealedCardOption must not.
        assert ser.option(RevealedCardOption(c)) == {"type": "revealed_card", "name": "food_5"}


# --- _serialize_card counters flag ---------------------------------------

class TestSerializeCardCountersFlag:

    def test_default_includes_counters(self):
        c = food(3); c.counters = 2
        assert Serializer._serialize_card(c) == {"name": "food_3", "counters": 2}

    def test_explicit_true_includes_counters(self):
        c = food(3); c.counters = 0
        assert Serializer._serialize_card(c, counters=True) == {"name": "food_3", "counters": 0}

    def test_explicit_false_omits_counters(self):
        c = food(3); c.counters = 5
        wire = Serializer._serialize_card(c, counters=False)
        assert wire == {"name": "food_3"}
        assert "counters" not in wire


# --- PromptBuilder ergonomics --------------------------------------------

class TestPromptBuilderRevealed:

    def test_add_revealed_cards_appends_per_card(self):
        cards = [food(3), food(5), food(7)]
        pb = PromptBuilder("X").add_revealed_cards(cards)
        half = pb._half()
        assert len(half.options) == 3
        for opt, c in zip(half.options, cards):
            assert isinstance(opt, RevealedCardOption)
            assert opt.card is c

    def test_must_select_defaults_to_1(self):
        pb = PromptBuilder("X").add(TextOption("Yes"))
        assert pb._half().must_select == 1

    def test_must_select_setter_propagates(self):
        pb = PromptBuilder("X").add(TextOption("Yes")).must_select(3)
        assert pb._half().must_select == 3

    def test_must_select_accepts_zero(self):
        """must_select=0 is a valid view-only reveal (player responds with [])."""
        pb = PromptBuilder("X").add_revealed_cards([food(3)]).must_select(0)
        half = pb._half()
        assert half.must_select == 0

    def test_must_select_rejects_negative(self):
        pb = PromptBuilder("X")
        with pytest.raises(AssertionError):
            pb.must_select(-1)


# --- Serializer.prompt_message wire shape --------------------------------

class TestPromptMessage:

    def test_default_must_select_omitted_from_wire(self):
        """Back-compat: a default (must_select=1) prompt produces wire output
        identical to the pre-feature shape (no must_select key)."""
        g = minimal_game()
        ser = _serializer(g)
        half = PromptHalf("X", [TextOption("Yes"), TextOption("No")])
        msg = ser.prompt_message(half)
        assert "must_select" not in msg
        assert msg["type"] == "prompt"
        assert msg["text"] == "X"
        assert msg["options"] == [{"type": "text", "text": "Yes"}, {"type": "text", "text": "No"}]
        assert "context" not in msg

    def test_multi_select_includes_must_select(self):
        g = minimal_game()
        ser = _serializer(g)
        half = PromptHalf("Pick 2", [TextOption("A"), TextOption("B"), TextOption("C")],
                          must_select=2)
        msg = ser.prompt_message(half)
        assert msg["must_select"] == 2

    def test_context_round_trips(self):
        g = minimal_game()
        c = food(3)
        g.players[PID.RED].hand.slot(c)
        ser = _serializer(g)
        half = PromptHalf("Y", [TextOption("OK")], context=[CardOption(c)])
        msg = ser.prompt_message(half)
        assert msg["context"] == [{"type": "card", "slot": "red_hand", "index": 0}]


# --- ScriptedPlayer multi-select consumption -----------------------------

class TestScriptedPlayerMultiSelect:

    def test_single_select_returns_bare_option(self):
        sp = ScriptedPlayer([TextOption("a")])
        result = sp.prompt(PromptHalf("X", [TextOption("a")]))
        assert isinstance(result, Option)
        assert not isinstance(result, list)
        assert result == TextOption("a")

    def test_multi_select_returns_list_of_must_select(self):
        sp = ScriptedPlayer([TextOption("a"), TextOption("b")])
        result = sp.prompt(PromptHalf("X", [TextOption("a"), TextOption("b")], must_select=2))
        assert isinstance(result, list)
        assert len(result) == 2
        assert result == [TextOption("a"), TextOption("b")]

    def test_multi_select_underflow_raises(self):
        """If the script doesn't have enough options for must_select, IndexError."""
        sp = ScriptedPlayer([TextOption("a")])
        with pytest.raises(IndexError):
            sp.prompt(PromptHalf("X", [TextOption("a")], must_select=2))

    def test_must_select_zero_returns_empty_list_without_popping(self):
        """must_select=0 → empty list, no script consumption."""
        sp = ScriptedPlayer([TextOption("untouched")])
        c = food(3)
        result = sp.prompt(PromptHalf("X", [RevealedCardOption(c)], must_select=0))
        assert result == []
        assert sp.script == [TextOption("untouched")]


# --- PromptHalf construction (positive cases only) -----------------------
#
# Note: PromptHalf is a plain @dataclass with no __post_init__, so it does
# not enforce invariants like "options must be homogeneously RevealedCardOption
# or not", "RevealedCardOption is forbidden in context", or "must_select >= 0".
# PromptBuilder.must_select() does assert n >= 0, but constructing a PromptHalf
# directly with must_select=-1 or with mixed option types is currently accepted.
# Those invariant tests were deleted; if the project wants them enforced, the
# fix is to add a __post_init__ to PromptHalf, not to bring the tests back.

class TestPromptHalfConstruction:

    def test_pure_revealed_options_allowed(self):
        half = PromptHalf("X", [RevealedCardOption(food(3)), RevealedCardOption(food(5))],
                          must_select=2)
        assert len(half.options) == 2

    def test_pure_non_revealed_options_allowed(self):
        half = PromptHalf("X", [TextOption("Yes"), TextOption("No")])
        assert len(half.options) == 2


# --- Piñata Stick (weapon_3) end-to-end ----------------------------------

class TestPinataStick:

    def test_yes_deals_damage_and_shows_hand_as_options_must_select_0(self):
        """Yes branch: 3 damage; reveal prompt has the opponent's hand cards as
        RevealedCardOption entries in `options` with must_select=0 (view-only).
        No 'OK' text button — the empty-list response IS the acknowledgement."""
        g = minimal_game()
        pina = weapon_3()
        g.players[PID.RED].weapon_slots[0].wield(pina)
        a, b, c = food(3), food(5), food(7)
        g.players[PID.BLUE].hand.slot(a, b, c)
        g.players[PID.BLUE].hp = 10
        before = count_all_cards(g)

        captured: list[PromptHalf] = []
        from interact.player import ScriptedPlayer
        from interact.interpret import AggregateInterpreter

        class _RP(ScriptedPlayer):
            def prompt(self, half):
                captured.append(half)
                return super().prompt(half)

        # must_select=0 reveal consumes no script entries.
        red = _RP([TextOption("Yes")])
        blue = _RP([])
        run(g, do(Discard(PID.RED, pina, "test")), AggregateInterpreter(red, blue))

        assert g.players[PID.BLUE].hp == 7
        assert count_all_cards(g) == before
        assert len(captured) == 2
        reveal = captured[1]
        assert reveal.text == "Opponent's hand:"
        assert reveal.must_select == 0
        assert reveal.context == []
        names = sorted(opt.card.name for opt in reveal.options)
        assert names == sorted(["food_3", "food_5", "food_7"])
        for opt in reveal.options:
            assert isinstance(opt, RevealedCardOption)

    def test_reveal_prompt_serializes_cards_in_options_by_name(self):
        """The reveal serializes as {type: prompt, options: [revealed_card...],
        must_select: 0} — no context, no slot/index, no counters."""
        g = minimal_game()
        pina = weapon_3()
        g.players[PID.RED].weapon_slots[0].wield(pina)
        a, b = food(3), food(7)
        g.players[PID.BLUE].hand.slot(a, b)
        g.players[PID.BLUE].hp = 10

        ser = _serializer(g)
        captured: list[PromptHalf] = []
        from interact.player import ScriptedPlayer
        from interact.interpret import AggregateInterpreter

        class _RP(ScriptedPlayer):
            def prompt(self, half):
                captured.append(half)
                return super().prompt(half)

        red = _RP([TextOption("Yes")])
        blue = _RP([])
        run(g, do(Discard(PID.RED, pina, "test")), AggregateInterpreter(red, blue))

        reveal = captured[1]
        wire = ser.prompt_message(reveal)
        assert wire["must_select"] == 0
        assert "context" not in wire
        names_on_wire = sorted(item["name"] for item in wire["options"])
        assert names_on_wire == sorted(["food_3", "food_7"])
        for item in wire["options"]:
            assert item["type"] == "revealed_card"
            assert "counters" not in item
            assert "slot" not in item

    def test_yes_with_empty_opp_hand_still_issues_empty_reveal(self):
        """Current behavior: Piñata Stick on Yes ALWAYS issues the reveal prompt,
        even when the opponent's hand is empty after the damage. The reveal carries
        options=[] and must_select=0 — functionally a no-op the client immediately
        replies to with [].

        Note: Detective (good_role_8) takes the opposite approach and skips reveal
        when there's nothing to show. The asymmetry is worth flagging."""
        g = minimal_game()
        pina = weapon_3()
        g.players[PID.RED].weapon_slots[0].wield(pina)
        g.players[PID.BLUE].hp = 10
        # BLUE hand intentionally empty.

        captured: list[PromptHalf] = []
        from interact.player import ScriptedPlayer
        from interact.interpret import AggregateInterpreter

        class _RP(ScriptedPlayer):
            def prompt(self, half):
                captured.append(half)
                return super().prompt(half)

        red = _RP([TextOption("Yes")])
        blue = _RP([])
        run(g, do(Discard(PID.RED, pina, "test")), AggregateInterpreter(red, blue))

        assert g.players[PID.BLUE].hp == 7
        assert len(captured) == 2  # Yes/No prompt + empty reveal prompt
        reveal = captured[1]
        assert reveal.text == "Opponent's hand:"
        assert reveal.options == []
        assert reveal.must_select == 0

    def test_no_skips_damage_and_reveal(self):
        g = minimal_game()
        pina = weapon_3()
        g.players[PID.RED].weapon_slots[0].wield(pina)
        g.players[PID.BLUE].hp = 10
        g.players[PID.BLUE].hand.slot(food(3))

        run(g, do(Discard(PID.RED, pina, "test")), interp(TextOption("No")))

        assert g.players[PID.BLUE].hp == 10  # no damage


# --- Detective (good_role_8) end-to-end ----------------------------------

class TestDetectiveReveal:

    def test_reveal_lists_deck_and_refresh_as_revealed_cards(self):
        """Detective's reveal: TWO prompts, one per pile (deck shuffled, then
        refresh shuffled). Each prompt has must_select=0 and lists that pile's
        cards as RevealedCardOption entries — no acknowledgement button.

        The deck prompt is shuffled because Detective lets the player see WHICH
        cards are in the deck, not the draw order (which would let them peek at
        upcoming draws). Refresh is also shuffled for consistency."""
        g = minimal_game()
        det = detective()
        g.players[PID.RED].equipment.slot(det)
        g.players[PID.RED].deck.slot(food(3), food(5))
        g.players[PID.RED].refresh.slot(food(7))

        captured: list[PromptHalf] = []
        from interact.player import ScriptedPlayer
        from interact.interpret import AggregateInterpreter

        # must_select=0 reveal consumes no script entries.
        red = type("RP", (ScriptedPlayer,), {
            "prompt": lambda self, half: (captured.append(half) or ScriptedPlayer.prompt(self, half)),
        })([])
        blue = ScriptedPlayer([])
        run(g, do(Discard(PID.RED, det, "test")), AggregateInterpreter(red, blue))

        assert len(captured) == 2
        deck_reveal, refresh_reveal = captured

        assert deck_reveal.text == "Detective: Your deck (shuffled)"
        assert deck_reveal.must_select == 0
        assert deck_reveal.context == []
        assert sorted(opt.card.name for opt in deck_reveal.options) == sorted(["food_3", "food_5"])
        for opt in deck_reveal.options:
            assert isinstance(opt, RevealedCardOption)

        assert refresh_reveal.text == "Detective: Your refresh pile (shuffled)"
        assert refresh_reveal.must_select == 0
        assert refresh_reveal.context == []
        assert [opt.card.name for opt in refresh_reveal.options] == ["food_7"]
        assert isinstance(refresh_reveal.options[0], RevealedCardOption)

    def test_reveal_skipped_when_deck_and_refresh_empty(self):
        """No prompt if there are no cards to reveal."""
        g = minimal_game()
        det = detective()
        g.players[PID.RED].equipment.slot(det)
        # deck + refresh intentionally empty

        captured: list[PromptHalf] = []
        from interact.player import ScriptedPlayer
        from interact.interpret import AggregateInterpreter

        red = type("RP", (ScriptedPlayer,), {
            "prompt": lambda self, half: (captured.append(half) or ScriptedPlayer.prompt(self, half)),
        })([])
        blue = ScriptedPlayer([])
        run(g, do(Discard(PID.RED, det, "test")), AggregateInterpreter(red, blue))

        assert captured == []


# --- High Priestess (major_2) — must_select=2 end-to-end ----------------

class TestHighPriestessMultiSelect:

    def _setup(self):
        g = minimal_game()
        hp_card = the_high_priestess()
        # Place priestess on the action field so Resolve has the right context.
        g.players[PID.RED].action_field.top_distant.slot(hp_card)
        # Pool: deck has food_3, food_5; refresh has food_7, enemy_3; discard has weapon_1.
        g.players[PID.RED].deck.slot(food(3), food(5))
        g.players[PID.RED].refresh.slot(food(7), enemy(3))
        g.players[PID.RED].discard.slot(weapon_1())
        g.players[PID.RED].hp = 10
        g.players[PID.BLUE].hp = 20
        return g, hp_card

    def test_naming_two_refresh_cards_yields_two_choice_prompts(self):
        """Naming both food_7 and enemy_3 (both in refresh) triggers 2
        follow-up choice prompts. The player heals from each."""
        g, hp_card = self._setup()

        # ScriptedPlayer pops must_select=2 entries for the naming prompt,
        # then one entry per follow-up choice prompt.
        from cards import food as food_factory, enemy as enemy_factory
        pick_food_7 = RevealedCardOption(food_factory(7))
        pick_enemy_3 = RevealedCardOption(enemy_factory(3))

        ip = interp(
            pick_food_7, pick_enemy_3,   # 2 picks for must_select=2 naming prompt
            TextOption("Heal 7"),         # follow-up #1 (food_7 hit)
            TextOption("Heal 7"),         # follow-up #2 (enemy_3 hit)
        )
        run(g, do(Resolve(PID.RED, hp_card, "test")), ip)
        # Both names were in refresh → 2 hits → 2 heals of 7 each (capped at hp_ceiling=20)
        assert g.players[PID.RED].hp == 20

    def test_naming_only_misses_no_followup(self):
        """If neither name is in refresh, no follow-up prompts are issued."""
        g, hp_card = self._setup()
        # Pick food_3 and food_5 — neither is in refresh.
        pick_a = RevealedCardOption(food(3))
        pick_b = RevealedCardOption(food(5))
        # Only the multi-select prompt is consumed. (If a follow-up were emitted
        # we'd be missing a script entry and ScriptedPlayer would raise.)
        ip = interp(pick_a, pick_b)
        run(g, do(Resolve(PID.RED, hp_card, "test")), ip)
        assert g.players[PID.RED].hp == 10  # unchanged

    def test_pool_offers_one_representative_per_name_with_must_select_2(self):
        """The reveal prompt's options have exactly one RevealedCardOption per
        distinct card name across deck/refresh/discard, with must_select=2."""
        g, hp_card = self._setup()

        captured: list[PromptHalf] = []
        from interact.player import ScriptedPlayer
        from interact.interpret import AggregateInterpreter

        class _RP(ScriptedPlayer):
            def prompt(self, half):
                captured.append(half)
                return super().prompt(half)

        # Script: 2 entries for the must_select=2 naming prompt; neither name
        # is in refresh so no follow-ups are issued.
        red = _RP([RevealedCardOption(food(3)), RevealedCardOption(food(5))])
        blue = _RP([])
        run(g, do(Resolve(PID.RED, hp_card, "test")), AggregateInterpreter(red, blue))

        # First prompt is the naming prompt.
        naming = captured[0]
        assert naming.must_select == 2
        names = sorted(opt.card.name for opt in naming.options)
        # 5 distinct names: food_3, food_5, food_7, enemy_3, weapon_1
        assert names == sorted(["food_3", "food_5", "food_7", "enemy_3", "weapon_1"])
        for opt in naming.options:
            assert isinstance(opt, RevealedCardOption)


# --- Wire envelope round-trip --------------------------------------------

class TestWireRoundTrip:

    def test_prompt_message_must_select_omitted_for_default(self):
        """Byte-for-byte back-compat: default must_select=1 produces no key."""
        g = minimal_game()
        ser = _serializer(g)
        half = PromptHalf("Pick", [TextOption("a"), TextOption("b")])
        msg = ser.prompt_message(half)
        assert "must_select" not in msg

    def _make_synced_conn(self):
        """A fake Connection whose recv() blocks until send() has been called
        and a response has been queued. This avoids the race where the listener
        thread tries to resolve a queued response before the prompt() call has
        registered _last_options."""
        import queue
        import threading
        from interact.connection import Connection

        class _SyncedConn(Connection):
            def __init__(self):
                self._inbox: queue.Queue = queue.Queue()
                self.sent: list[dict] = []
                self._send_event = threading.Event()
            def send(self, msg):
                self.sent.append(msg)
                self._send_event.set()
            def recv(self):
                msg = self._inbox.get()
                if msg is None:
                    raise ConnectionError("closed")
                return msg
            def push_response(self, msg):
                """Block until prompt has been sent, then push the response."""
                self._send_event.wait()
                self._send_event.clear()
                self._inbox.put(msg)
            def close(self):
                self._inbox.put(None)

        return _SyncedConn()

    def test_remoteplayer_listen_dispatches_options_array_to_list(self):
        """RemotePlayer._listen routes {options: [...]} responses into a list."""
        import threading
        from interact.player import RemotePlayer

        g = minimal_game()
        ser = _serializer(g)
        half = PromptHalf(
            "X",
            [TextOption("a"), TextOption("b"), TextOption("c")],
            must_select=2,
        )
        conn = self._make_synced_conn()
        rp = RemotePlayer(conn, ser, PID.RED, "test")

        result_box: list = []
        t = threading.Thread(target=lambda: result_box.append(rp.prompt(half)))
        t.start()
        conn.push_response({"type": "response", "options": [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "c"},
        ]})
        t.join(timeout=5)
        assert not t.is_alive()
        assert isinstance(result_box[0], list)
        assert result_box[0] == [TextOption("a"), TextOption("c")]
        conn.close()

    def test_remoteplayer_listen_empty_options_for_must_select_0(self):
        """must_select=0 reveal: client responds with {options: []}, which
        decodes into an empty Python list. The card factory's `yield` ignores it."""
        import threading
        from interact.player import RemotePlayer

        g = minimal_game()
        ser = _serializer(g)
        # Pure RevealedCardOption options, must_select=0.
        half = PromptHalf(
            "Reveal",
            [RevealedCardOption(food(3)), RevealedCardOption(food(7))],
            must_select=0,
        )
        wire = ser.prompt_message(half)
        assert wire["must_select"] == 0
        assert "context" not in wire
        assert [item["type"] for item in wire["options"]] == ["revealed_card", "revealed_card"]

        conn = self._make_synced_conn()
        rp = RemotePlayer(conn, ser, PID.RED, "test")
        result_box: list = []
        t = threading.Thread(target=lambda: result_box.append(rp.prompt(half)))
        t.start()
        conn.push_response({"type": "response", "options": []})
        t.join(timeout=5)
        assert not t.is_alive()
        assert result_box[0] == []
        conn.close()

    def test_remoteplayer_listen_single_option_back_compat(self):
        """Single-select wire form ({option: ...}) still returns a bare Option."""
        import threading
        from interact.player import RemotePlayer

        g = minimal_game()
        ser = _serializer(g)
        half = PromptHalf("X", [TextOption("Yes"), TextOption("No")])
        conn = self._make_synced_conn()
        rp = RemotePlayer(conn, ser, PID.RED, "test")

        result_box: list = []
        t = threading.Thread(target=lambda: result_box.append(rp.prompt(half)))
        t.start()
        conn.push_response({"type": "response", "option": {"type": "text", "text": "Yes"}})
        t.join(timeout=5)
        assert not t.is_alive()
        assert result_box[0] == TextOption("Yes")
        assert not isinstance(result_box[0], list)
        conn.close()
