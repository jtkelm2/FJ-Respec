"""Unit tests for PromptBuilder: build/decode round-trip, add_if, add_cards, both, either."""
import pytest
from core.type import (
    PID, PKind, Card, CardType, PromptBuilder,
)


def _card(name: str, level: int = 1) -> Card:
    return Card(name, name.title(), "", level, (CardType.FOOD,), False, False)


class TestBuildDecode:
    def test_round_trip_single_option(self):
        pb = PromptBuilder("Pick one").add("Alpha", "a")
        prompt = pb.build(PID.RED)
        assert prompt.kind == PKind.EITHER
        assert PID.RED in prompt.for_player
        assert prompt.for_player[PID.RED].options == ["Alpha"]

        assert pb.decode({PID.RED: 0}, PID.RED) == "a"

    def test_round_trip_multiple_options(self):
        pb = (PromptBuilder("Choose")
              .add("X", 10)
              .add("Y", 20)
              .add("Z", 30))
        prompt = pb.build(PID.BLUE)
        assert prompt.for_player[PID.BLUE].options == ["X", "Y", "Z"]
        assert prompt.for_player[PID.BLUE].text == "Choose"

        assert pb.decode({PID.BLUE: 0}, PID.BLUE) == 10
        assert pb.decode({PID.BLUE: 1}, PID.BLUE) == 20
        assert pb.decode({PID.BLUE: 2}, PID.BLUE) == 30

    def test_decode_out_of_bounds_raises(self):
        pb = PromptBuilder("Pick").add("Only", "only")
        with pytest.raises(IndexError):
            pb.decode({PID.RED: 1}, PID.RED)

    def test_tags_can_be_none(self):
        pb = PromptBuilder("?").add("Skip", None).add("Do it", "do")
        assert pb.decode({PID.RED: 0}, PID.RED) is None
        assert pb.decode({PID.RED: 1}, PID.RED) == "do"


class TestAddIf:
    def test_true_condition_adds_option(self):
        pb = PromptBuilder("?").add_if(True, "Yes", "y")
        assert pb.build(PID.RED).for_player[PID.RED].options == ["Yes"]
        assert pb.decode({PID.RED: 0}, PID.RED) == "y"

    def test_false_condition_skips_option(self):
        pb = (PromptBuilder("?")
              .add("A", 1)
              .add_if(False, "B", 2)
              .add("C", 3))
        opts = pb.build(PID.RED).for_player[PID.RED].options
        assert opts == ["A", "C"]
        assert pb.decode({PID.RED: 0}, PID.RED) == 1
        assert pb.decode({PID.RED: 1}, PID.RED) == 3

    def test_all_false_gives_empty_options(self):
        pb = (PromptBuilder("?")
              .add_if(False, "X", 1)
              .add_if(False, "Y", 2))
        assert pb.build(PID.RED).for_player[PID.RED].options == []


class TestAddCards:
    def test_uses_display_name_by_default(self):
        cards = [_card("apple"), _card("bread")]
        pb = PromptBuilder("Pick card").add_cards(cards)
        opts = pb.build(PID.RED).for_player[PID.RED].options
        assert opts == ["Apple", "Bread"]

    def test_decode_returns_card_objects(self):
        cards = [_card("apple"), _card("bread")]
        pb = PromptBuilder("Pick card").add_cards(cards)
        assert pb.decode({PID.RED: 0}, PID.RED) is cards[0]
        assert pb.decode({PID.RED: 1}, PID.RED) is cards[1]

    def test_custom_label_fn(self):
        cards = [_card("apple", level=3)]
        pb = PromptBuilder("?").add_cards(
            cards, label_fn=lambda c: f"Lv.{c.level} {c.display_name}"
        )
        assert pb.build(PID.RED).for_player[PID.RED].options == ["Lv.3 Apple"]
        assert pb.decode({PID.RED: 0}, PID.RED) is cards[0]

    def test_cards_plus_done_sentinel(self):
        cards = [_card("x"), _card("y")]
        pb = PromptBuilder("?").add_cards(cards).add("Done", None)
        assert pb.decode({PID.RED: 0}, PID.RED) is cards[0]
        assert pb.decode({PID.RED: 1}, PID.RED) is cards[1]
        assert pb.decode({PID.RED: 2}, PID.RED) is None


class TestChaining:
    def test_methods_return_self(self):
        pb = PromptBuilder("?")
        assert pb.add("A", 1) is pb
        assert pb.add_if(True, "B", 2) is pb
        assert pb.add_cards([_card("c")]) is pb


class TestBoth:
    def test_single_builder_prompts_both_players(self):
        pb = PromptBuilder("Claim?").add("No", False).add("Yes", True)
        prompt = PromptBuilder.both(pb)
        assert prompt.kind == PKind.BOTH
        assert set(prompt.for_player.keys()) == {PID.RED, PID.BLUE}
        for pid in PID:
            assert prompt.for_player[pid].text == "Claim?"
            assert prompt.for_player[pid].options == ["No", "Yes"]

    def test_single_builder_decode_per_player(self):
        pb = PromptBuilder("?").add("No", False).add("Yes", True)
        response = {PID.RED: 0, PID.BLUE: 1}
        assert pb.decode(response, PID.RED) is False
        assert pb.decode(response, PID.BLUE) is True

    def test_two_builders_asymmetric(self):
        red_pb = PromptBuilder("Sacrifice?").add("Yes", "sac").add("No", "pass")
        blue_pb = PromptBuilder("Attack?").add("Strike", "atk").add("Wait", "wait")
        prompt = PromptBuilder.both(red_pb, blue_pb)
        assert prompt.kind == PKind.BOTH
        assert prompt.for_player[PID.RED].text == "Sacrifice?"
        assert prompt.for_player[PID.RED].options == ["Yes", "No"]
        assert prompt.for_player[PID.BLUE].text == "Attack?"
        assert prompt.for_player[PID.BLUE].options == ["Strike", "Wait"]

        response = {PID.RED: 1, PID.BLUE: 0}
        assert red_pb.decode(response, PID.RED) == "pass"
        assert blue_pb.decode(response, PID.BLUE) == "atk"


class TestEither:
    def test_single_builder_prompts_both_players(self):
        pb = PromptBuilder("Race?").add("Go", "go")
        prompt = PromptBuilder.either(pb)
        assert prompt.kind == PKind.EITHER
        assert set(prompt.for_player.keys()) == {PID.RED, PID.BLUE}

    def test_single_builder_decode_responder(self):
        pb = PromptBuilder("?").add("A", 1).add("B", 2)
        # Only the responder's PID is in the response
        assert pb.decode({PID.BLUE: 1}, PID.BLUE) == 2

    def test_two_builders_asymmetric(self):
        red_pb = PromptBuilder("Red Q").add("R1", "r1")
        blue_pb = PromptBuilder("Blue Q").add("B1", "b1").add("B2", "b2")
        prompt = PromptBuilder.either(red_pb, blue_pb)
        assert prompt.kind == PKind.EITHER
        assert prompt.for_player[PID.RED].text == "Red Q"
        assert prompt.for_player[PID.BLUE].options == ["B1", "B2"]

    def test_single_pid_same_as_build(self):
        """build_either with one builder is structurally identical to build for that PID."""
        pb = PromptBuilder("?").add("X", 1)
        via_build = pb.build(PID.RED)
        via_either = PromptBuilder.either(pb)
        # either gives both PIDs; build gives one — but the content is the same
        assert via_build.for_player[PID.RED] == via_either.for_player[PID.RED]
        assert via_build.kind == via_either.kind  # both PKind.EITHER
