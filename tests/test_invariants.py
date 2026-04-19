"""
Cross-cutting invariants: properties that must hold across any phase or action.

The cardinal rule: cards are never created or destroyed.
"""

from core.type import PID, Slot, Death, Alignment, TextOption, SlotOption, WeaponSlotOption
from core.engine import do
from interact.interpret import run
from helpers import interp, count_all_cards, initial_game
from cards import food, enemy
from combat import resolve_combat
from phase.refresh import refresh_phase


class TestRefreshDealCounts:
    """Verify exact card counts dealt during refresh.

    Kills mutants: _deal_action_cards [:-1] -> [:+1] and [:-1] -> [:-2].
    """

    def test_refresh_deals_3_action_cards_from_4_empty_slots(self):
        g = initial_game(seed=42)
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
        g = initial_game(seed=42)
        g.players[PID.RED].action_field.top_distant.slot(food(99))

        run(g, refresh_phase(), interp())

        af = g.players[PID.RED].action_field
        filled = [s for s in af.slots_in_fill_order() if not s.is_empty()]
        assert len(filled) == 3


class TestSetupRoleAssignment:
    """Verify alignment distribution from setup_phase.

    Kills mutant: alignments[1] -> alignments[2] (wrong alignment for BLUE).
    """

    def test_blue_gets_second_alignment_not_third(self):
        """The 3-slot alignment pool is [GOOD, GOOD, EVIL], shuffled; BLUE
        takes slot 1. With seed=1 under the new setup trajectory, RED=EVIL
        and BLUE=GOOD, so swapping index 1 for 2 would give BLUE=EVIL."""
        g = initial_game(seed=1)
        assert g.players[PID.RED].alignment == Alignment.EVIL
        assert g.players[PID.BLUE].alignment == Alignment.GOOD


class TestDeadPlayerSkipped:
    """Dead players must be skipped during dealing phases.

    Kills mutant: _deal_hand__mutmut_3 (not p.is_dead -> p.is_dead).
    """

    def test_refresh_does_not_deal_to_dead_player(self):
        g = initial_game(seed=42)
        run(g, do(Death(PID.RED)), interp())
        assert g.players[PID.RED].is_dead

        run(g, refresh_phase(), interp())

        assert len(g.players[PID.RED].hand.cards) == 0
        assert len(g.players[PID.BLUE].hand.cards) == 4


class TestCardConservation:
    """Total card count must be identical before and after any operation."""

    def test_conservation_across_refresh_phase(self):
        g = initial_game(seed=42)
        before = count_all_cards(g)
        run(g, refresh_phase(), interp())
        assert count_all_cards(g) == before

    def test_conservation_across_fists_combat(self):
        g = initial_game(seed=42)
        e = enemy(5)
        g.players[PID.RED].hand.slot(e)
        before = count_all_cards(g)
        run(g, resolve_combat(PID.RED, e), interp(SlotOption(g.players[PID.RED].discard)))
        assert count_all_cards(g) == before

    def test_conservation_across_weapon_combat(self):
        from core.type import WeaponSlot
        from cards import weapon

        g = initial_game(seed=42)
        e = enemy(5)
        g.players[PID.RED].hand.slot(e)
        ws = WeaponSlot("t")
        ws._weapon_slot.slot(weapon(6))
        ws.killstack.slot(enemy(6))
        g.players[PID.RED].weapon_slots = [ws]

        before = count_all_cards(g)
        run(g, resolve_combat(PID.RED, e), interp(WeaponSlotOption(ws)))
        assert count_all_cards(g) == before

    def test_conservation_across_manipulation_dump(self):
        g = initial_game(seed=42)
        before = count_all_cards(g)
        from phase.manipulation import manipulation_phase
        run(g, manipulation_phase(), interp(TextOption("Dump"), blue=[TextOption("Dump")]))
        assert count_all_cards(g) == before

    def test_conservation_across_refresh_then_manipulation(self):
        """Full refresh -> manipulation sequence preserves card count."""
        g = initial_game(seed=42)
        before = count_all_cards(g)

        run(g, refresh_phase(), interp())

        from phase.manipulation import manipulation_phase
        run(g, manipulation_phase(),
            interp(TextOption("Dump"),
                   TextOption("Discard"), TextOption("Discard"),
                   TextOption("Discard"), TextOption("Discard"),
                   blue=[TextOption("Dump"),
                         TextOption("Discard"), TextOption("Discard"),
                         TextOption("Discard"), TextOption("Discard")]))

        assert count_all_cards(g) == before
