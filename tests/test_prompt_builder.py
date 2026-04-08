"""Unit tests for PromptBuilder: build, add, add_if, add_cards, both, either."""
import pytest
from core.type import (
    PID, PKind, Card, CardType, PromptBuilder, TextOption, CardOption,
)


def _card(name: str, level: int = 1) -> Card:
    return Card(name, name.title(), "", level, (CardType.FOOD,), False, False)


class TestBuild:
    def test_single_option(self):
        pb = PromptBuilder("Pick one").add(TextOption("Alpha"))
        prompt = pb.build(PID.RED)
        assert prompt.kind == PKind.EITHER
        assert PID.RED in prompt.for_player
        assert prompt.for_player[PID.RED].options == [TextOption("Alpha")]

    def test_multiple_options(self):
        pb = (PromptBuilder("Choose")
              .add(TextOption("X"))
              .add(TextOption("Y"))
              .add(TextOption("Z")))
        prompt = pb.build(PID.BLUE)
        assert prompt.for_player[PID.BLUE].options == [
            TextOption("X"), TextOption("Y"), TextOption("Z")
        ]
        assert prompt.for_player[PID.BLUE].text == "Choose"


class TestAddIf:
    def test_true_condition_adds_option(self):
        pb = PromptBuilder("?").add_if(True, TextOption("Yes"))
        assert pb.build(PID.RED).for_player[PID.RED].options == [TextOption("Yes")]

    def test_false_condition_skips_option(self):
        pb = (PromptBuilder("?")
              .add(TextOption("A"))
              .add_if(False, TextOption("B"))
              .add(TextOption("C")))
        opts = pb.build(PID.RED).for_player[PID.RED].options
        assert opts == [TextOption("A"), TextOption("C")]

    def test_all_false_gives_empty_options(self):
        pb = (PromptBuilder("?")
              .add_if(False, TextOption("X"))
              .add_if(False, TextOption("Y")))
        assert pb.build(PID.RED).for_player[PID.RED].options == []


class TestAddCards:
    def test_adds_card_options(self):
        cards = [_card("apple"), _card("bread")]
        pb = PromptBuilder("Pick card").add_cards(cards)
        opts = pb.build(PID.RED).for_player[PID.RED].options
        assert opts == [CardOption(cards[0]), CardOption(cards[1])]

    def test_cards_plus_done_sentinel(self):
        cards = [_card("x"), _card("y")]
        pb = PromptBuilder("?").add_cards(cards).add(TextOption("Done"))
        opts = pb.build(PID.RED).for_player[PID.RED].options
        assert opts[0] == CardOption(cards[0])
        assert opts[1] == CardOption(cards[1])
        assert opts[2] == TextOption("Done")


class TestChaining:
    def test_methods_return_self(self):
        pb = PromptBuilder("?")
        assert pb.add(TextOption("A")) is pb
        assert pb.add_if(True, TextOption("B")) is pb
        assert pb.add_cards([_card("c")]) is pb


class TestBoth:
    def test_single_builder_prompts_both_players(self):
        pb = PromptBuilder("Claim?").add(TextOption("No")).add(TextOption("Yes"))
        prompt = PromptBuilder.both(pb)
        assert prompt.kind == PKind.BOTH
        assert set(prompt.for_player.keys()) == {PID.RED, PID.BLUE}
        for pid in PID:
            assert prompt.for_player[pid].text == "Claim?"
            assert prompt.for_player[pid].options == [TextOption("No"), TextOption("Yes")]

    def test_two_builders_asymmetric(self):
        red_pb = PromptBuilder("Sacrifice?").add(TextOption("Yes")).add(TextOption("No"))
        blue_pb = PromptBuilder("Attack?").add(TextOption("Strike")).add(TextOption("Wait"))
        prompt = PromptBuilder.both(red_pb, blue_pb)
        assert prompt.kind == PKind.BOTH
        assert prompt.for_player[PID.RED].text == "Sacrifice?"
        assert prompt.for_player[PID.RED].options == [TextOption("Yes"), TextOption("No")]
        assert prompt.for_player[PID.BLUE].text == "Attack?"
        assert prompt.for_player[PID.BLUE].options == [TextOption("Strike"), TextOption("Wait")]


class TestEither:
    def test_single_builder_prompts_both_players(self):
        pb = PromptBuilder("Race?").add(TextOption("Go"))
        prompt = PromptBuilder.either(pb)
        assert prompt.kind == PKind.EITHER
        assert set(prompt.for_player.keys()) == {PID.RED, PID.BLUE}

    def test_two_builders_asymmetric(self):
        red_pb = PromptBuilder("Red Q").add(TextOption("R1"))
        blue_pb = PromptBuilder("Blue Q").add(TextOption("B1")).add(TextOption("B2"))
        prompt = PromptBuilder.either(red_pb, blue_pb)
        assert prompt.kind == PKind.EITHER
        assert prompt.for_player[PID.RED].text == "Red Q"
        assert prompt.for_player[PID.BLUE].options == [TextOption("B1"), TextOption("B2")]

    def test_single_pid_same_as_build(self):
        """build_either with one builder is structurally identical to build for that PID."""
        pb = PromptBuilder("?").add(TextOption("X"))
        via_build = pb.build(PID.RED)
        via_either = PromptBuilder.either(pb)
        assert via_build.for_player[PID.RED] == via_either.for_player[PID.RED]
        assert via_build.kind == via_either.kind
