"""
Combat resolution: weapon selection, damage, slay mechanics.

Metamorphic relation:  damage = max(0, enemy_level - sharpness)
  - increasing sharpness monotonically decreases damage (floor 0)
  - damage is always non-negative
"""

import pytest
from core.type import PID, CardType, WeaponSlot, TextOption, WeaponSlotOption
from interact.interpret import run
from combat import resolve_combat, can_use_weapon
from helpers import interp
from cards import enemy, weapon, food
from phase.setup import create_initial_state


def _armed(sharpness_level):
    """Create a WeaponSlot with the given sharpness.

    Weapon level matches sharpness_level so min(weapon, kill) = sharpness_level.
    """
    ws = WeaponSlot()
    ws._weapon_slot.slot(weapon(max(sharpness_level, 1)))
    if sharpness_level > 0:
        ws.killstack.slot(enemy(sharpness_level))
    return ws


# ---------- fists ----------

class TestFistsCombat:

    @pytest.mark.parametrize("enemy_lv", [1, 5, 10, 14])
    def test_fists_damage_equals_enemy_level(self, enemy_lv):
        g = create_initial_state(seed=42)
        e = enemy(enemy_lv)
        g.players[PID.RED].hand.slot(e)
        run(g, resolve_combat(PID.RED, e), interp(TextOption(f"Fists ({enemy_lv} dmg)")))
        assert g.players[PID.RED].hp == 20 - enemy_lv

    def test_fists_sends_enemy_to_discard(self):
        g = create_initial_state(seed=42)
        e = enemy(3)
        g.players[PID.RED].hand.slot(e)
        run(g, resolve_combat(PID.RED, e), interp(TextOption("Fists (3 dmg)")))
        assert e in g.players[PID.RED].discard.cards

    def test_fists_lethal_kills_player(self):
        g = create_initial_state(seed=42)
        e = enemy(20)
        g.players[PID.RED].hand.slot(e)
        run(g, resolve_combat(PID.RED, e), interp(TextOption("Fists (20 dmg)")))
        assert g.players[PID.RED].is_dead


# ---------- weapon combat ----------

class TestWeaponCombat:

    def test_weapon_reduces_damage(self):
        g = create_initial_state(seed=42)
        e = enemy(10)
        g.players[PID.RED].hand.slot(e)
        g.players[PID.RED].weapon_slots = [_armed(7)]

        run(g, resolve_combat(PID.RED, e), interp(WeaponSlotOption(g.players[PID.RED].weapon_slots[0])))
        assert g.players[PID.RED].hp == 20 - 3  # max(0, 10-7) = 3

    def test_weapon_sends_enemy_to_killstack(self):
        g = create_initial_state(seed=42)
        e = enemy(5)
        g.players[PID.RED].hand.slot(e)
        ws = _armed(5)
        g.players[PID.RED].weapon_slots = [ws]

        run(g, resolve_combat(PID.RED, e), interp(WeaponSlotOption(ws)))
        assert e in ws.killstack.cards

    @pytest.mark.parametrize("enemy_lv,sharpness", [
        (1, 1), (5, 5), (10, 10), (14, 14),  # exact match
        (5, 10),                               # oversharp
    ])
    def test_zero_damage_when_sharpness_ge_enemy(self, enemy_lv, sharpness):
        g = create_initial_state(seed=42)
        e = enemy(enemy_lv)
        g.players[PID.RED].hand.slot(e)
        g.players[PID.RED].weapon_slots = [_armed(sharpness)]

        run(g, resolve_combat(PID.RED, e), interp(WeaponSlotOption(g.players[PID.RED].weapon_slots[0])))
        assert g.players[PID.RED].hp == 20


# ---------- metamorphic: monotonicity ----------

class TestDamageMonotonicity:
    """Higher sharpness -> less or equal damage, for any fixed enemy level."""

    def test_increasing_sharpness_never_increases_damage(self):
        enemy_lv = 10
        prev_damage = enemy_lv + 1  # sentinel above max possible

        for sharp in range(0, enemy_lv + 3):
            g = create_initial_state(seed=42)
            e = enemy(enemy_lv)
            g.players[PID.RED].hand.slot(e)

            if sharp == 0:
                # fists
                run(g, resolve_combat(PID.RED, e), interp(TextOption(f"Fists ({enemy_lv} dmg)")))
            else:
                g.players[PID.RED].weapon_slots = [_armed(sharp)]
                run(g, resolve_combat(PID.RED, e), interp(WeaponSlotOption(g.players[PID.RED].weapon_slots[0])))

            actual_damage = 20 - g.players[PID.RED].hp
            assert 0 <= actual_damage <= prev_damage
            prev_damage = actual_damage


# ---------- can_use_weapon ----------

class TestCanUseWeapon:

    def test_empty_killstack_sharpness_equals_weapon_level(self):
        ws = WeaponSlot()
        ws._weapon_slot.slot(weapon(5))
        assert ws.sharpness() == 5
        assert can_use_weapon(ws, enemy(5))

    def test_sharpness_dulls_with_kills(self):
        ws = WeaponSlot()
        ws._weapon_slot.slot(weapon(10))
        ws.killstack.slot(enemy(3))
        assert ws.sharpness() == 3  # min(10, 3)
        ws.killstack.slot(enemy(7))
        assert ws.sharpness() == 7  # min(10, 7), new top

    def test_sharpness_capped_by_weapon_level(self):
        ws = WeaponSlot()
        ws._weapon_slot.slot(weapon(5))
        ws.killstack.slot(enemy(10))
        assert ws.sharpness() == 5  # can't exceed weapon level

    @pytest.mark.parametrize("sharp,elv,expected", [
        (5, 5, True),   # exact match
        (6, 5, True),   # oversharp
        (4, 5, False),  # undersharp
    ])
    def test_usability_at_boundary(self, sharp, elv, expected):
        ws = _armed(sharp)
        assert can_use_weapon(ws, enemy(elv)) == expected


# ---------- weapon slot indexing ----------

class TestWeaponSlotSelection:

    def test_second_weapon_slot_selected_by_choice_2(self):
        """Kills mutant: weapon_slots[choice-1] -> weapon_slots[choice-2].

        With 2 weapon slots and choice=2, choice-1=1 (correct) vs choice-2=0 (wrong).
        The two weapons have different sharpness, so damage differs.
        """
        g = create_initial_state(seed=42)
        e = enemy(10)
        g.players[PID.RED].hand.slot(e)

        ws0 = _armed(3)   # sharpness 3 -> 7 damage
        ws1 = _armed(9)   # sharpness 9 -> 1 damage
        g.players[PID.RED].weapon_slots = [ws0, ws1]

        run(g, resolve_combat(PID.RED, e), interp(WeaponSlotOption(ws1)))
        assert g.players[PID.RED].hp == 20 - 1  # 10 - 9 = 1 damage
        assert e in ws1.killstack.cards
