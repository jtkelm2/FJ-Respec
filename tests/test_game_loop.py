"""
Game loop: phase cycling, win conditions, world claims, StartPhase reset.
"""

import pytest
from core.type import (
    PID, Alignment, Outcome, GameResult, GameOver, StartPhase, Phase,
    WORLD_NAME, Card, CardType,
)
from core.engine import run, do
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


# ── StartPhase action ─────────────────────────────────────────

class TestStartPhaseAction:

    def test_refresh_sets_satiated(self):
        g = minimal_game()
        for pid in PID:
            g.players[pid].is_satiated = False

        run(g, do(StartPhase(Phase.REFRESH)), interp())
        for pid in PID:
            assert g.players[pid].is_satiated is True

    def test_manipulation_is_noop(self):
        g = minimal_game()
        g.players[PID.RED].is_satiated = True
        g.players[PID.RED].action_plays_left = 0

        run(g, do(StartPhase(Phase.MANIPULATION)), interp())
        # Nothing changed
        assert g.players[PID.RED].is_satiated is True
        assert g.players[PID.RED].action_plays_left == 0

    def test_action_resets_plays_and_first_play(self):
        g = minimal_game()
        for pid in PID:
            p = g.players[pid]
            p.first_play_done = True
            p.action_plays_left = 0

        run(g, do(StartPhase(Phase.ACTION)), interp())
        for pid in PID:
            p = g.players[pid]
            assert p.first_play_done is False
            assert p.action_plays_left == 3

    def test_action_does_not_touch_satiation(self):
        g = minimal_game()
        g.players[PID.RED].is_satiated = True

        run(g, do(StartPhase(Phase.ACTION)), interp())
        assert g.players[PID.RED].is_satiated is True


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

    def test_good_killed_good(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.GOOD
        g.players[PID.BLUE].is_dead = True

        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.GOOD_KILLED_GOOD
        assert result.winners == (PID.RED,)

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

        # Only one claims
        g.players[PID.RED].claims_world_killed = True
        g.players[PID.BLUE].claims_world_killed = False
        assert g.check_game_over() is None

        # Both claim
        g.players[PID.BLUE].claims_world_killed = True
        result = g.check_game_over()
        assert result is not None
        assert result.outcome == Outcome.MUTUAL_GOOD_WIN
        assert set(result.winners) == {PID.RED, PID.BLUE}

    def test_mutual_good_win_blocked_if_evil_present(self):
        g = minimal_game()
        g.players[PID.RED].alignment = Alignment.GOOD
        g.players[PID.BLUE].alignment = Alignment.EVIL
        g.players[PID.RED].discard.slot(_world_card())
        g.players[PID.BLUE].discard.slot(_world_card())
        g.players[PID.RED].claims_world_killed = True
        g.players[PID.BLUE].claims_world_killed = True

        assert g.check_game_over() is None


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

    def test_player_can_claim(self):
        g = minimal_game()
        # RED: No(0), BLUE: Yes(1)
        run(g, _offer_world_claims, interp(0, blue=[1]))
        assert g.players[PID.RED].claims_world_killed is False
        assert g.players[PID.BLUE].claims_world_killed is True

    def test_already_claimed_not_asked_again(self):
        g = minimal_game()
        g.players[PID.RED].claims_world_killed = True
        # Only BLUE gets prompted: No(0)
        run(g, _offer_world_claims, interp(blue=[0]))
        assert g.players[PID.RED].claims_world_killed is True
        assert g.players[PID.BLUE].claims_world_killed is False

    def test_dead_player_not_asked(self):
        g = minimal_game()
        g.players[PID.RED].is_dead = True
        # Only BLUE gets prompted: Yes(1)
        run(g, _offer_world_claims, interp(blue=[1]))
        assert g.players[PID.BLUE].claims_world_killed is True


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
        # World claims: Yes(1) each.
        red_choices = [1, 0, 0, 0, 0, 0, 0, 0, 0, 1]
        blue_choices = [1, 0, 0, 0, 0, 0, 0, 0, 0, 1]

        run(g, game_loop(), interp(*red_choices, blue=blue_choices))
        assert g.is_over
        assert g.game_result is not None
        assert g.game_result.outcome == Outcome.MUTUAL_GOOD_WIN
        assert set(g.game_result.winners) == {PID.RED, PID.BLUE}
