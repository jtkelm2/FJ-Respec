"""
simultaneously(): async effect combinator.

Merges per-player Ask prompts into AskEither, advancing whichever
player the interpreter answers for.
"""

import pytest
from core.type import PID, Ask, AskBoth, PromptHalf, PKind, Prompt, PlayerState
from core.engine import run, simultaneously
from helpers import interp, minimal_game


class TestSimultaneously:

    def test_both_single_prompt_effects_complete(self):
        results = {}

        def red_eff(g):
            r = yield Ask(PID.RED, "Pick:", ["a", "b"])
            results[PID.RED] = r[PID.RED]

        def blue_eff(g):
            r = yield Ask(PID.BLUE, "Pick:", ["x", "y"])
            results[PID.BLUE] = r[PID.BLUE]

        g = minimal_game()
        run(g, simultaneously({PID.RED: red_eff, PID.BLUE: blue_eff}),
            interp(0, blue=[1]))

        assert results[PID.RED] == 0
        assert results[PID.BLUE] == 1

    def test_multi_step_effects_interleave(self):
        choices = {PID.RED: [], PID.BLUE: []}

        def red_eff(g):
            r = yield Ask(PID.RED, "R1:", ["a"])
            choices[PID.RED].append(r[PID.RED])
            r = yield Ask(PID.RED, "R2:", ["b"])
            choices[PID.RED].append(r[PID.RED])

        def blue_eff(g):
            r = yield Ask(PID.BLUE, "B1:", ["x"])
            choices[PID.BLUE].append(r[PID.BLUE])

        g = minimal_game()
        run(g, simultaneously({PID.RED: red_eff, PID.BLUE: blue_eff}),
            interp(0, 0, blue=[0]))

        assert len(choices[PID.RED]) == 2
        assert len(choices[PID.BLUE]) == 1

    def test_one_effect_finishes_immediately(self):
        result = {}

        def red_eff(g):
            return
            yield  # makes it a generator

        def blue_eff(g):
            r = yield Ask(PID.BLUE, "Pick:", ["x"])
            result[PID.BLUE] = r[PID.BLUE]

        g = minimal_game()
        run(g, simultaneously({PID.RED: red_eff, PID.BLUE: blue_eff}),
            interp(blue=[0]))

        assert result[PID.BLUE] == 0

    def test_both_finish_immediately(self):
        def red_eff(g):
            return
            yield

        def blue_eff(g):
            return
            yield

        g = minimal_game()
        # No prompts, no interpreter choices needed
        run(g, simultaneously({PID.RED: red_eff, PID.BLUE: blue_eff}),
            interp())

    def test_rejects_non_either_prompt(self):
        """simultaneously requires each effect to yield single-player Ask prompts.

        Yielding a BOTH prompt must trigger the assertion in _extract.
        Kills mutant: simultaneously__mutmut_4 (and -> or).
        """
        def red_eff(g):
            # Yield a BOTH prompt — violates simultaneously's contract
            yield AskBoth({
                PID.RED: PromptHalf("R:", ["a"]),
                PID.BLUE: PromptHalf("B:", ["x"]),
            })

        def blue_eff(g):
            return
            yield

        g = minimal_game()
        with pytest.raises(AssertionError):
            run(g, simultaneously({PID.RED: red_eff, PID.BLUE: blue_eff}),
                interp(0, blue=[0]))
