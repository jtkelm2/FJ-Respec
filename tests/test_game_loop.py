"""
Game loop: phase cycling, win conditions, world claims, StartPhase/EndPhase.
"""

import pytest
from core.type import (
    PID, Alignment, Outcome, GameResult, GameOver, StartPhase, Phase,
    WORLD_NAME, Card, CardType,
)
from core.engine import do
from interact.interpret import run
from cards import enemy, food, weapon
from phase.game import game_loop, _settle, _offer_world_claims
from phase.setup import create_initial_state
from helpers import interp, minimal_game, count_all_cards


def _world_card():
    return Card(WORLD_NAME, "The World", "", 21, (CardType.ENEMY,), True, False)


# ── GameOver action ───────────────────────────────────────────

class TestGameOverAction:

    def test_sets_game_result(self):
        g = minimal_game()
        result = GameResult((PID.RED,), Outcome.GOOD_KILLED_EVIL)
        run(g, do(GameOver(result)), interp())
        assert g.game_result is result
        assert g.is_over

    def test_exhaustion_result(self):
        g = minimal_game()
        result = GameResult((), Outcome.EXHAUSTION)
        run(g, do(GameOver(result)), interp())
        assert g.game_result is not None
        assert g.game_result.winners == ()


# ── StartPhase/EndPhase are no-ops in engine ──────────────────

class TestStartPhaseAction:
    """StartPhase and EndPhase are hookable no-ops; actual resets live in the phases."""

    def test_start_phase_is_noop(self):
        g = minimal_game()
        g.players[PID.RED].is_satiated = False
        g.players[PID.RED].first_play_done = True
        g.players[PID.RED].action_plays_left = 0

        run(g, do(StartPhase(Phase.REFRESH)), interp())
        # Nothing changed — StartPhase is a pure hook point
        assert g.players[PID.RED].is_satiated is False
        assert g.players[PID.RED].first_play_done is True
        assert g.players[PID.RED].action_plays_left == 0


# ── Phase-level resets ────────────────────────────────────────

class TestPhaseResets:
    """Resets are done directly in the phase functions, not via StartPhase."""

    def test_refresh_sets_satiated(self):
        """refresh_phase sets is_satiated = True for all players."""
        g = minimal_game()
        for pid in PID:
            g.players[pid].is_satiated = False
            # Need cards for refresh to not exhaust
            for _ in range(10):
                g.players[pid].deck.slot(food(1))

        from phase.refresh import refresh_phase
        run(g, refresh_phase(), interp())
        for pid in PID:
            assert g.players[pid].is_satiated is False

    def test_action_resets_plays(self):
        """action_phase resets first_play_done and action_plays_left."""
        g = minimal_game()
        for pid in PID:
            p = g.players[pid]
            p.first_play_done = True
            p.action_plays_left = 0
            p.action_field.top_distant.slot(food(1))
            p.action_field.top_hidden.slot(food(1))
            p.action_field.bottom_hidden.slot(food(1))

        from phase.action import action_phase
        # no-LR(0), 3x slot(0) per player
        run(g, action_phase(), interp(0, 0, 0, 0, blue=[0, 0, 0, 0]))
        for pid in PID:
            assert g.players[pid].action_plays_left == 0
            assert g.players[pid].first_play_done is True


# ── GameState.check_game_over ─────────────────────────────────

class TestCheckGameOver:

    def test_no_death_no_result(self):
        g = minimal_game()
        assert g.check_game_over() is None

    def test_evil_killed_good(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL
        g.players[PID.RED].is_dead = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.EVIL_KILLED_GOOD
        assert result.winners == (PID.BLUE,)

    def test_good_killed_evil(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL
        g.players[PID.BLUE].is_dead = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.GOOD_KILLED_EVIL
        assert result.winners == (PID.RED,)

    def test_good_killed_good_no_winners(self):
        """When a Good player dies to another Good player, nobody wins."""
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.GOOD
        g.players[PID.BLUE].is_dead = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.GOOD_KILLED_GOOD
        assert result.winners == ()

    def test_good_good_mutual_death(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.GOOD
        g.players[PID.RED].is_dead = True
        g.players[PID.BLUE].is_dead = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.GOOD_GOOD_MUTUAL_DEATH
        assert result.winners == ()

    def test_good_evil_mutual_death(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL
        g.players[PID.RED].is_dead = True
        g.players[PID.BLUE].is_dead = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.GOOD_EVIL_MUTUAL_DEATH
        assert result.winners == ()

    def test_mutual_good_win_requires_both_claims_and_both_worlds(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.GOOD

        # 2 Worlds killed (in discard piles)
        g.players[PID.RED].discard.slot(_world_card())
        g.players[PID.BLUE].discard.slot(_world_card())

        # Only one claims — game continues
        g.players[PID.RED].claims_world_killed = True
        g.players[PID.BLUE].claims_world_killed = False
        assert g.check_game_over() is None

        # Both claim — mutual good win
        g.players[PID.BLUE].claims_world_killed = True
        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.MUTUAL_GOOD_WIN
        assert set(result.winners) == {PID.RED, PID.BLUE}

    def test_evil_thwarted_when_evil_claims_with_worlds_dead(self):
        """Evil player claims alongside Good — Evil gets exposed."""
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL
        g.players[PID.RED].discard.slot(_world_card())
        g.players[PID.BLUE].discard.slot(_world_card())
        g.players[PID.RED].claims_world_killed = True
        g.players[PID.BLUE].claims_world_killed = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.EVIL_THWARTED
        assert result.winners == (PID.RED,)

    def test_good_thwarted_when_both_good_claim_but_worlds_not_dead(self):
        """Both Good claim but Worlds aren't actually dead."""
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.GOOD
        g.players[PID.RED].claims_world_killed = True
        g.players[PID.BLUE].claims_world_killed = True
        # No worlds in discard/killstack

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.GOOD_THWARTED
        assert result.winners == ()

    def test_evil_thwarted_when_claims_but_worlds_not_dead(self):
        """Evil claims alongside Good but Worlds aren't dead — Evil exposed."""
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL
        g.players[PID.RED].claims_world_killed = True
        g.players[PID.BLUE].claims_world_killed = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.EVIL_THWARTED
        assert result.winners == (PID.RED,)


# ── get_worlds_killed ─────────────────────────────────────────

class TestGetWorldsKilled:

    def test_counts_worlds_in_discard(self):
        g = minimal_game()
        g.players[PID.RED].discard.slot(_world_card())
        assert g.get_worlds_killed() == 1

    def test_counts_worlds_in_killstack(self):
        g = minimal_game()
        ws = g.players[PID.RED].weapon_slots[0]
        ws._weapon_slot.slot(weapon(21))
        ws.killstack.slot(_world_card())
        assert g.get_worlds_killed() == 1

    def test_counts_across_players(self):
        g = minimal_game()
        g.players[PID.RED].discard.slot(_world_card())
        g.players[PID.BLUE].discard.slot(_world_card())
        assert g.get_worlds_killed() == 2

    def test_zero_when_no_worlds(self):
        g = minimal_game()
        assert g.get_worlds_killed() == 0


# ── _offer_world_claims ───────────────────────────────────────

class TestOfferWorldClaims:

    def test_neither_claimed_asks_both(self):
        """When neither has claimed, AskBoth is used."""
        g = minimal_game()
        # Both prompted simultaneously: RED=No(0), BLUE=Yes(1)
        run(g, _offer_world_claims, interp(0, blue=[1]))
        assert g.players[PID.RED].claims_world_killed is False
        assert g.players[PID.BLUE].claims_world_killed is True

    def test_one_already_claimed_asks_other(self):
        """When one has claimed, only the other is prompted."""
        g = minimal_game()
        g.players[PID.RED].claims_world_killed = True
        # BLUE gets AskEither: No(0)
        run(g, _offer_world_claims, interp(blue=[0]))
        assert g.players[PID.RED].claims_world_killed is True
        assert g.players[PID.BLUE].claims_world_killed is False

    def test_both_already_claimed_no_prompt(self):
        """When both have claimed, no prompts at all."""
        g = minimal_game()
        g.players[PID.RED].claims_world_killed = True
        g.players[PID.BLUE].claims_world_killed = True
        run(g, _offer_world_claims, interp())


# ── _settle ───────────────────────────────────────────────────

class TestSettle:

    def test_settle_dispatches_game_over_on_death(self):
        g = minimal_game()
        g.players[PID.RED].is_dead = True
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL

        run(g, _settle, interp())
        assert g.is_over
        assert g.game_result is not None
        assert g.game_result.outcome == Outcome.EVIL_KILLED_GOOD

    def test_settle_noop_when_alive(self):
        g = minimal_game()
        run(g, _settle, interp())
        assert not g.is_over


# ── Full game loop integration ────────────────────────────────

class TestGameLoopIntegration:

    def test_death_in_action_phase_ends_game(self):
        g = minimal_game()
        g.players[PID.RED].hp = 1
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL

        for pid in PID:
            for _ in range(10):
                g.players[pid].deck.slot(food(1))

        g.players[PID.RED].action_field.top_distant.slot(enemy(20))

        # Refresh: auto. Manip: both dump. Action: RED picks enemy, dies.
        # World claims not reached (death exits first).
        red_choices = [1, 0, 0, 0, 0, 0, 0, 0]
        blue_choices = [1, 0, 0, 0, 0]

        run(g, game_loop(), interp(*red_choices, blue=blue_choices))
        assert g.is_over
        assert g.game_result is not None
        assert g.game_result.outcome == Outcome.EVIL_KILLED_GOOD
        assert g.game_result.winners == (PID.BLUE,)

    def test_exhaustion_kills_both(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.GOOD
        run(g, game_loop(), interp())
        assert g.is_over
        assert g.game_result is not None
        assert g.game_result.outcome == Outcome.GOOD_GOOD_MUTUAL_DEATH

    def test_mutual_good_win_via_world_claims(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.GOOD

        for pid in PID:
            for _ in range(10):
                g.players[pid].deck.slot(food(1))

        # Pre-kill both Worlds
        g.players[PID.RED].discard.slot(_world_card())
        g.players[PID.BLUE].discard.slot(_world_card())

        # Refresh: auto.
        # Manip: dump(1) + 4x discard(0) = 5 each.
        # Action: no-LR(0) + 3x slot(0) = 4 each.
        # World claims (AskBoth): Yes(1) each.
        red_choices = [1, 0, 0, 0, 0, 0, 0, 0, 0, 1]
        blue_choices = [1, 0, 0, 0, 0, 0, 0, 0, 0, 1]

        run(g, game_loop(), interp(*red_choices, blue=blue_choices))
        assert g.is_over
        assert g.game_result is not None
        assert g.game_result.outcome == Outcome.MUTUAL_GOOD_WIN
        assert set(g.game_result.winners) == {PID.RED, PID.BLUE}
