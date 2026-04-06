"""
HP system: damage, healing, clamping, and death.

Boundary analysis of the pipeline:
  Damage/Heal -> SetHP -> clamp(floor, ceiling) -> Death if hp <= 0
"""

import pytest
from core.type import PID, Damage, Heal, SetHP
from core.engine import do
from interact.interpret import run
from helpers import interp
from phase.setup import create_initial_state


# ---------- damage boundaries ----------

class TestDamageBoundaries:

    @pytest.mark.parametrize("amount,expected_hp,expected_dead", [
        (0,   20,   False),  # zero damage: no-op
        (1,   19,   False),  # minimal
        (19,  1,    False),  # one HP remaining
        (20,  0,    True),   # exact lethal
        (21,  -1,   True),   # overkill by 1
        (999, -979, True),   # massive overkill
    ])
    def test_damage_at_boundary(self, amount, expected_hp, expected_dead):
        g = create_initial_state(seed=42)
        run(g, do(Damage(PID.RED, amount, "test")), interp())
        p = g.players[PID.RED]
        assert p.hp == expected_hp
        assert p.is_dead == expected_dead


# ---------- heal boundaries ----------

class TestHealBoundaries:

    @pytest.mark.parametrize("damage_first,heal,expected_hp", [
        (10, 0,  10),   # zero heal
        (10, 1,  11),   # minimal heal
        (10, 10, 20),   # exact restore to starting HP
        (10, 15, 25),   # overheal past starting HP (no default ceiling)
    ])
    def test_heal_at_boundary(self, damage_first, heal, expected_hp):
        g = create_initial_state(seed=42)
        run(g, do(Damage(PID.RED, damage_first, "test")), interp())
        run(g, do(Heal(PID.RED, heal, "test")), interp())
        assert g.players[PID.RED].hp == expected_hp


# ---------- clamping ----------

class TestHPClamping:

    def test_floor_prevents_death(self):
        g = create_initial_state(seed=42)
        g.players[PID.RED].hp_floor = 1
        run(g, do(Damage(PID.RED, 999, "test")), interp())
        p = g.players[PID.RED]
        assert p.hp == 1
        assert not p.is_dead

    def test_floor_at_zero_still_triggers_death(self):
        """Floor clamps to 0, but hp <= 0 still triggers Death."""
        g = create_initial_state(seed=42)
        g.players[PID.RED].hp_floor = 0
        run(g, do(Damage(PID.RED, 999, "test")), interp())
        p = g.players[PID.RED]
        assert p.hp == 0
        assert p.is_dead

    def test_ceiling_caps_heal(self):
        g = create_initial_state(seed=42)
        g.players[PID.RED].hp_ceiling = 20
        run(g, do(Heal(PID.RED, 100, "test")), interp())
        assert g.players[PID.RED].hp == 20

    def test_ceiling_caps_sethp_directly(self):
        g = create_initial_state(seed=42)
        g.players[PID.RED].hp_ceiling = 15
        run(g, do(SetHP(PID.RED, 100, "test")), interp())
        assert g.players[PID.RED].hp == 15

    def test_floor_and_ceiling_interact(self):
        """Floor clamps damage, ceiling clamps subsequent heal."""
        g = create_initial_state(seed=42)
        g.players[PID.RED].hp_floor = 5
        g.players[PID.RED].hp_ceiling = 25
        run(g, do(Damage(PID.RED, 100, "test")), interp())
        assert g.players[PID.RED].hp == 5

        run(g, do(Heal(PID.RED, 100, "test")), interp())
        assert g.players[PID.RED].hp == 25


# ---------- multi-step composition ----------

class TestHPComposition:

    def test_damage_heal_damage_kills(self):
        g = create_initial_state(seed=42)
        run(g, do(Damage(PID.RED, 15, "test")), interp())   # 20 -> 5
        run(g, do(Heal(PID.RED, 10, "test")), interp())     # 5 -> 15
        run(g, do(Damage(PID.RED, 15, "test")), interp())   # 15 -> 0
        assert g.players[PID.RED].hp == 0
        assert g.players[PID.RED].is_dead

    def test_death_is_permanent_after_heal(self):
        """Once dead, healing changes HP but is_dead stays True."""
        g = create_initial_state(seed=42)
        run(g, do(Damage(PID.RED, 20, "test")), interp())
        assert g.players[PID.RED].is_dead

        run(g, do(Heal(PID.RED, 10, "test")), interp())
        assert g.players[PID.RED].hp == 10
        assert g.players[PID.RED].is_dead  # still dead

    def test_players_have_independent_hp(self):
        g = create_initial_state(seed=42)
        run(g, do(Damage(PID.RED, 15, "test")), interp())
        run(g, do(Damage(PID.BLUE, 5, "test")), interp())
        assert g.players[PID.RED].hp == 5
        assert g.players[PID.BLUE].hp == 15
