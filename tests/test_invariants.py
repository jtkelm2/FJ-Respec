"""
Cross-cutting invariants: properties that must hold across any phase or action.

The cardinal rule: cards are never created or destroyed.
"""

from core.type import PID, Slot, Death, Alignment
from core.engine import run, do
from helpers import interp, count_all_cards
from cards import food, enemy
from combat import resolve_combat
from phase.setup import create_initial_state
from phase.refresh import refresh_phase


class TestRefreshDealCounts:
    """Verify exact card counts dealt during refresh.

    Kills mutants: _deal_action_cards [:-1] -> [:+1] and [:-1] -> [:-2].
    """

    def test_refresh_deals_3_action_cards_from_4_empty_slots(self):
        g = create_initial_state(seed=42)
        run(g, refresh_phase(), interp())

        for pid in PID:
            af = g.players[pid].action_field
            filled = [s for s in af.slots_in_fill_order() if not s.is_empty()]
            assert len(filled) == 3, (
                f"{pid}: expected 3 action cards (4 empty slots minus 1), "
                f"got {len(filled)}"
            )

    def test_refresh_deals_fewer_action_cards_when_slots_occupied(self):
        """With 1 slot already filled, 3 empty -> deals 2 (3 - 1)."""
        g = create_initial_state(seed=42)
        # Fill one action slot for RED before refresh
        g.players[PID.RED].action_field.top_distant.slot(food(99))

        run(g, refresh_phase(), interp())

        af = g.players[PID.RED].action_field
        filled = [s for s in af.slots_in_fill_order() if not s.is_empty()]
        assert len(filled) == 3  # 1 pre-filled + 2 dealt (3 empty - 1)


class TestSetupRoleAssignment:
    """Verify role distribution from create_initial_state.

    Kills mutant: roles[1] -> roles[2] (wrong role for BLUE).
    """

    def test_blue_gets_second_role_not_third(self):
        """Kills mutant: roles[1] -> roles[2].

        The 3-role pool is [good, good, evil]. After shuffle with seed=42,
        assert BLUE's specific alignment. The mutant changes which role
        index BLUE gets, which (for 2/3 of seeds) changes the alignment.
        """
        g = create_initial_state(seed=42)
        # Pin the exact alignment for this seed; if the mutant swaps
        # roles[1] with roles[2] and they differ, this assertion fails.
        assert g.players[PID.BLUE].alignment == Alignment.GOOD


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
        ws._weapon_slot.slot(weapon(6))
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
