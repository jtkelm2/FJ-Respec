"""
Cross-cutting invariants: properties that must hold across any phase or action.

The cardinal rule: cards are never created or destroyed.
"""

from core.type import PID, Slot, Death
from core.engine import run, do
from helpers import interp, count_all_cards
from cards import food, enemy
from combat import resolve_combat
from phase.setup import create_initial_state
from phase.refresh import refresh_phase


class TestDeadPlayerSkipped:
    """Dead players must be skipped during dealing phases.

    Kills mutant: _deal_hand__mutmut_3 (not p.is_dead -> p.is_dead).
    """

    def test_refresh_does_not_deal_to_dead_player(self):
        g = create_initial_state(seed=42)
        run(g, do(Death(PID.RED)), interp())
        assert g.players[PID.RED].is_dead

        run(g, refresh_phase(), interp())

        # Dead player should NOT receive hand cards
        assert len(g.players[PID.RED].hand.cards) == 0
        # Alive player still gets their hand
        assert len(g.players[PID.BLUE].hand.cards) == 4


class TestCardConservation:
    """Total card count must be identical before and after any operation."""

    def test_conservation_across_refresh_phase(self):
        g = create_initial_state(seed=42)
        before = count_all_cards(g)
        run(g, refresh_phase(), interp())
        assert count_all_cards(g) == before

    def test_conservation_across_fists_combat(self):
        g = create_initial_state(seed=42)
        e = enemy(5)
        g.players[PID.RED].hand.slot(e)
        before = count_all_cards(g)
        run(g, resolve_combat(PID.RED, e), interp(0))
        assert count_all_cards(g) == before

    def test_conservation_across_weapon_combat(self):
        from core.type import WeaponSlot
        from cards import weapon

        g = create_initial_state(seed=42)
        e = enemy(5)
        g.players[PID.RED].hand.slot(e)
        ws = WeaponSlot()
        ws.weapon = weapon(1)
        ws.killstack.slot(enemy(6))
        g.players[PID.RED].weapon_slots = [ws]

        before = count_all_cards(g)
        run(g, resolve_combat(PID.RED, e), interp(1))
        assert count_all_cards(g) == before

    def test_conservation_across_manipulation_dump(self):
        g = create_initial_state(seed=42)
        before = count_all_cards(g)
        from phase.manipulation import manipulation_phase
        # Both dump with empty hands
        run(g, manipulation_phase(), interp(1, blue=[1]))
        assert count_all_cards(g) == before

    def test_conservation_across_refresh_then_manipulation(self):
        """Full refresh -> manipulation sequence preserves card count."""
        g = create_initial_state(seed=42)
        before = count_all_cards(g)

        run(g, refresh_phase(), interp())

        # After refresh: both players have 4 hand cards, 3 action cards,
        # 2 manipulation cards. Now manipulate: both dump.
        # RED has 4 hand cards: 4 discard prompts. BLUE has 4 hand cards.
        # Script: RED picks Dump(1), discards all(0,0,0,0).
        #         BLUE picks Dump(1), discards all(0,0,0,0).
        # Interleaving: RED answered first, runs all dump prompts, then
        # post-manipulation (no prompts). Then BLUE answered, same.
        from phase.manipulation import manipulation_phase
        run(g, manipulation_phase(),
            interp(1, 0, 0, 0, 0, blue=[1, 0, 0, 0, 0]))

        assert count_all_cards(g) == before
