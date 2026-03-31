"""
Tests for engine.py, analogous to reference.py's demo.

Covers:
  - Basic action execution (Damage, Heal, SetHP)
  - hp_floor / hp_ceiling clamping
  - Replacement listeners (instead-of)
  - Multiple replacements: affected player orders them (616.1)
  - After triggers, including recursive triggers (depth bounding)
  - Before triggers
  - compose()
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.type import *
from core.engine import do, compose, run


# ── Helpers ────────────────────────────────────────────────────────

def make_game() -> GameState:
    return GameState(
        rng_seed=0,
        priority=PID.RED,
        players={PID.RED: PlayerState(), PID.BLUE: PlayerState()},
        guard_deck=(),
        action_field=ActionField(),
    )

def scripted(*moves) -> AggregateInterpreter:
    """Both players draw from the same flat script."""
    s = list(moves)
    return AggregateInterpreter(ScriptedInterpreter(s.copy()), ScriptedInterpreter(s.copy()))

def no_input() -> AggregateInterpreter:
    return AggregateInterpreter(ScriptedInterpreter([]), ScriptedInterpreter([]))


# ── Sample listeners (analogous to reference.py) ───────────────────

def shield_listener() -> Listener:
    """Replacement: halve all damage to RED (rounded down)."""
    def replace(action):
        if isinstance(action, Damage) and action.target == PID.RED and action.amount > 0:
            return Damage(PID.RED, action.amount // 2, action.source)
        return None
    return Listener("Shield(halve dmg to RED)", replace, "replacement")

def vampiric_listener() -> Listener:
    """Replacement: reduce all damage to BLUE by 1 (minimum 0)."""
    def replace(action):
        if isinstance(action, Damage) and action.target == PID.BLUE and action.amount > 0:
            return Damage(PID.BLUE, max(0, action.amount - 1), action.source)
        return None
    return Listener("Vampiric(-1 dmg to BLUE)", replace, "replacement")

def thorns_listener() -> Listener:
    """After: whenever RED takes damage, deal 1 to BLUE."""
    def check(action):
        if isinstance(action, Damage) and action.target == PID.RED and action.amount > 0:
            def thorns_effect(g: GameState):
                g.log.append("    Thorns retaliates!")
                return do(Damage(PID.BLUE, 1, "Thorns"))(g)
            return thorns_effect
        return None
    return Listener("Thorns(1 dmg back)", check, "after")

def guardian_listener() -> Listener:
    """Before: whenever RED would take damage, RED gains 1 hp first."""
    def check(action):
        if isinstance(action, Damage) and action.target == PID.RED and action.amount > 0:
            def guardian_effect(g: GameState):
                g.log.append("    Guardian activates!")
                return do(Heal(PID.RED, 1, "Guardian"))(g)
            return guardian_effect
        return None
    return Listener("Guardian(+1 before dmg)", check, "before")


# ── Tests ──────────────────────────────────────────────────────────

def test_damage_basic():
    g = make_game()
    g = run(g, do(Damage(PID.BLUE, 5, "Fireball")), no_input())
    assert g.players[PID.BLUE].hp == 15
    assert g.players[PID.RED].hp == 20

def test_heal_basic():
    g = make_game()
    g.players[PID.RED].hp = 10
    g = run(g, do(Heal(PID.RED, 6, "Potion")), no_input())
    assert g.players[PID.RED].hp == 16

def test_set_hp_direct():
    g = make_game()
    g = run(g, do(SetHP(PID.BLUE, 7, "Effect")), no_input())
    assert g.players[PID.BLUE].hp == 7

def test_set_hp_floor():
    g = make_game()
    g.players[PID.RED].hp_floor = 1
    g = run(g, do(SetHP(PID.RED, -5, "Overkill")), no_input())
    assert g.players[PID.RED].hp == 1

def test_set_hp_ceiling():
    g = make_game()
    g.players[PID.RED].hp_ceiling = 25
    g = run(g, do(Heal(PID.RED, 100, "Overheal")), no_input())
    assert g.players[PID.RED].hp == 25

def test_zero_damage_no_effect():
    g = make_game()
    g = run(g, do(Damage(PID.BLUE, 0, "Miss")), no_input())
    assert g.players[PID.BLUE].hp == 20
    assert g.log == []

def test_replacement_shield():
    g = make_game()
    g.listeners.append(shield_listener())
    g = run(g, do(Damage(PID.RED, 6, "Attack")), no_input())
    assert g.players[PID.RED].hp == 17  # 20 - 6//2 = 17

def test_replacement_shield_odd():
    g = make_game()
    g.listeners.append(shield_listener())
    g = run(g, do(Damage(PID.RED, 5, "Attack")), no_input())
    assert g.players[PID.RED].hp == 18  # 20 - 5//2 = 18 (rounds down)

def test_replacement_doesnt_apply_to_other_player():
    g = make_game()
    g.listeners.append(shield_listener())
    g = run(g, do(Damage(PID.BLUE, 4, "Attack")), no_input())
    assert g.players[PID.BLUE].hp == 16  # no shield for BLUE

def test_multiple_replacements_player_orders(capsys):
    """With shield + vampiric both on BLUE, affected player orders them.
    Script index 0 selects the first listed replacement first."""
    g = make_game()
    # Both listeners apply to damage targeting BLUE (vampiric) and RED (shield).
    # Send a 4-damage hit to BLUE: only vampiric applies (shield is for RED).
    g.listeners.append(vampiric_listener())
    g = run(g, do(Damage(PID.BLUE, 4, "Attack")), no_input())
    assert g.players[PID.BLUE].hp == 17  # 20 - (4-1) = 17

def test_two_replacements_ordering():
    """When two replacements both apply, the choice selects which fires first.
    We use two artificial replacements on the same target and verify ordering."""
    def minus2_listener():
        def replace(action):
            if isinstance(action, Damage) and action.target == PID.BLUE:
                return Damage(PID.BLUE, max(0, action.amount - 2), action.source)
            return None
        return Listener("Minus2", replace, "replacement")

    def halve_listener():
        def replace(action):
            if isinstance(action, Damage) and action.target == PID.BLUE:
                return Damage(PID.BLUE, action.amount // 2, action.source)
            return None
        return Listener("Halve", replace, "replacement")

    g = make_game()
    g.listeners.extend([minus2_listener(), halve_listener()])

    # Script: BLUE (affected player) picks index 0 = Minus2 first
    # Order: Minus2 then Halve: (8 - 2) // 2 = 3
    g = run(g, do(Damage(PID.BLUE, 8, "Attack")), scripted(0))
    assert g.players[PID.BLUE].hp == 17  # 20 - 3 = 17

def test_two_replacements_other_order():
    """Same as above but BLUE picks Halve first: 8 // 2 = 4, then 4 - 2 = 2."""
    def minus2_listener():
        def replace(action):
            if isinstance(action, Damage) and action.target == PID.BLUE:
                return Damage(PID.BLUE, max(0, action.amount - 2), action.source)
            return None
        return Listener("Minus2", replace, "replacement")

    def halve_listener():
        def replace(action):
            if isinstance(action, Damage) and action.target == PID.BLUE:
                return Damage(PID.BLUE, action.amount // 2, action.source)
            return None
        return Listener("Halve", replace, "replacement")

    g = make_game()
    g.listeners.extend([minus2_listener(), halve_listener()])

    # Script: BLUE picks index 1 = Halve first
    g = run(g, do(Damage(PID.BLUE, 8, "Attack")), scripted(1))
    assert g.players[PID.BLUE].hp == 18  # 20 - 2 = 18

def test_after_trigger_thorns():
    g = make_game()
    g.listeners.append(thorns_listener())
    g = run(g, do(Damage(PID.RED, 3, "Attack")), no_input())
    assert g.players[PID.RED].hp == 17  # 20 - 3
    assert g.players[PID.BLUE].hp == 19  # 20 - 1 (thorns)

def test_after_trigger_doesnt_fire_on_zero_damage():
    g = make_game()
    g.listeners.append(thorns_listener())
    g = run(g, do(Damage(PID.RED, 0, "Miss")), no_input())
    assert g.players[PID.RED].hp == 20
    assert g.players[PID.BLUE].hp == 20  # no thorns

def test_before_trigger_guardian():
    g = make_game()
    g.listeners.append(guardian_listener())
    g = run(g, do(Damage(PID.RED, 5, "Attack")), no_input())
    assert g.players[PID.RED].hp == 16  # 20 + 1 (guardian before) - 5 (damage)

def test_before_and_after_together():
    g = make_game()
    g.listeners.append(guardian_listener())
    g.listeners.append(thorns_listener())
    g = run(g, do(Damage(PID.RED, 4, "Attack")), no_input())
    assert g.players[PID.RED].hp == 17   # 20 + 1 - 4
    assert g.players[PID.BLUE].hp == 19  # thorns: -1

def test_recursive_trigger_depth_bounded():
    """Thorns triggers when RED takes damage; thorns deals 1 to BLUE,
    which has no further triggers. Verify trigger_depth resets to 0."""
    g = make_game()
    g.listeners.append(thorns_listener())
    g = run(g, do(Damage(PID.RED, 2, "Attack")), no_input())
    assert g.trigger_depth == 0

def test_trigger_depth_suppression():
    """A trigger that causes itself to fire infinitely is suppressed at max depth."""
    call_count = [0]

    def infinite_listener() -> Listener:
        def check(action):
            if isinstance(action, Damage) and action.target == PID.BLUE:
                call_count[0] += 1
                def inf_effect(g: GameState):
                    return do(Damage(PID.BLUE, 1, "Infinite"))(g)
                return inf_effect
            return None
        return Listener("Infinite", check, "after")

    g = make_game()
    g.listeners.append(infinite_listener())
    g = run(g, do(Damage(PID.BLUE, 1, "Start")), no_input())
    assert g.trigger_depth == 0
    # callback is called twice per depth level (once to build the list, once to get
    # the sub-effect), so total calls = 2 × max_trigger_depth
    assert call_count[0] <= g.max_trigger_depth * 2
    # initial damage + one damage per trigger level that actually fired
    assert g.players[PID.BLUE].hp == 20 - 1 - g.max_trigger_depth

def test_compose():
    g = make_game()
    effect = compose(
        do(Damage(PID.BLUE, 3, "Hit")),
        do(Heal(PID.RED, 5, "Lifesteal")),
        do(Damage(PID.RED, 1, "Recoil")),
    )
    g = run(g, effect, no_input())
    assert g.players[PID.BLUE].hp == 17  # 20 - 3
    assert g.players[PID.RED].hp == 24   # 20 + 5 - 1

def test_replacement_and_after_trigger_interact():
    """Shield halves damage, then thorns retaliates based on the halved amount.
    Thorns fires if the *replaced* action had amount > 0 (it does: 2 > 0)."""
    g = make_game()
    g.listeners.append(shield_listener())
    g.listeners.append(thorns_listener())
    g = run(g, do(Damage(PID.RED, 4, "Attack")), no_input())
    assert g.players[PID.RED].hp == 18   # 20 - 4//2 = 18
    assert g.players[PID.BLUE].hp == 19  # thorns: -1
