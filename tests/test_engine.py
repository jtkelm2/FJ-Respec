import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.type import *
from core.engine import run, do
from core.interpret import AggregateInterpreter, ScriptedInterpreter
from combat import resolve_combat, can_use_weapon
from cards import enemy, weapon, food
from phase.setup import create_initial_state

def _interp(*red_choices, blue=None):
    """Build an interpreter from scripted choice lists."""
    if blue is None:
        blue = []
    return AggregateInterpreter(
        ScriptedInterpreter(list(red_choices)),
        ScriptedInterpreter(list(blue)),
    )


# --- Damage / Heal / SetHP ---

def test_damage_reduces_hp():
    g = create_initial_state(seed=42)
    g = run(g, do(Damage(PID.RED, 5, "test")), _interp())
    assert g.players[PID.RED].hp == 15

def test_heal_increases_hp():
    g = create_initial_state(seed=42)
    g = run(g, do(Damage(PID.RED, 10, "test")), _interp())
    g = run(g, do(Heal(PID.RED, 3, "test")), _interp())
    assert g.players[PID.RED].hp == 13

def test_hp_floor_clamps():
    g = create_initial_state(seed=42)
    g.players[PID.RED].hp_floor = 5
    g = run(g, do(Damage(PID.RED, 100, "test")), _interp())
    assert g.players[PID.RED].hp == 5
    assert not g.players[PID.RED].is_dead

def test_hp_ceiling_clamps():
    g = create_initial_state(seed=42)
    g.players[PID.RED].hp_ceiling = 25
    g = run(g, do(Heal(PID.RED, 100, "test")), _interp())
    assert g.players[PID.RED].hp == 25

def test_lethal_damage_causes_death():
    g = create_initial_state(seed=42)
    g = run(g, do(Damage(PID.RED, 20, "test")), _interp())
    assert g.players[PID.RED].is_dead

def test_overkill_causes_death():
    g = create_initial_state(seed=42)
    g = run(g, do(Damage(PID.RED, 999, "test")), _interp())
    assert g.players[PID.RED].is_dead


# --- Discard ---

def test_discard_moves_card():
    g = create_initial_state(seed=42)
    card = food(9)
    g.players[PID.RED].hand.slot(card)
    g = run(g, do(Discard(PID.RED, card, "test")), _interp())
    assert card not in g.players[PID.RED].hand.cards
    assert card in g.players[PID.RED].discard.cards


# --- Combat (fists) ---

def test_combat_fists_full_damage():
    g = create_initial_state(seed=42)
    e = enemy(5)
    g.players[PID.RED].hand.slot(e)
    # choice 0 = fists
    g = run(g, resolve_combat(PID.RED, e), _interp(0))
    assert g.players[PID.RED].hp == 15  # 20 - 5
    # enemy discarded (fists -> Slay with ws=None -> Discard)
    assert e in g.players[PID.RED].discard.cards

def test_combat_weapon_reduces_damage():
    g = create_initial_state(seed=42)
    e = enemy(5)
    g.players[PID.RED].hand.slot(e)

    # Set up a weapon slot with a weapon and a kill to give sharpness
    ws = g.players[PID.RED].weapon_slots[0]
    ws.weapon = weapon(3)
    prev_kill = enemy(4)
    ws.killstack.slot(prev_kill)  # sharpness = 4

    # choice 1 = first weapon slot
    g = run(g, resolve_combat(PID.RED, e), _interp(1))
    assert g.players[PID.RED].hp == 19  # 20 - max(0, 5-4) = 19
    # enemy goes to killstack
    assert e in ws.killstack.cards

def test_combat_weapon_zero_damage():
    g = create_initial_state(seed=42)
    e = enemy(3)
    g.players[PID.RED].hand.slot(e)

    ws = g.players[PID.RED].weapon_slots[0]
    ws.weapon = weapon(2)
    prev_kill = enemy(5)
    ws.killstack.slot(prev_kill)  # sharpness = 5 >= 3

    g = run(g, resolve_combat(PID.RED, e), _interp(1))
    assert g.players[PID.RED].hp == 20  # no damage


# --- can_use_weapon ---

def test_can_use_weapon_true():
    ws = WeaponSlot()
    ws.weapon = weapon(1)
    kill = enemy(6)
    ws.killstack.slot(kill)
    assert can_use_weapon(ws, enemy(5))

def test_can_use_weapon_false_empty_killstack():
    ws = WeaponSlot()
    ws.weapon = weapon(1)
    assert not can_use_weapon(ws, enemy(1))


# --- Mutable defaults isolation ---

def test_player_states_have_independent_slots():
    p1 = PlayerState()
    p2 = PlayerState()
    card = food(1)
    p1.hand.slot(card)
    assert card not in p2.hand.cards
    assert p1.equipment is not p2.equipment
    assert p1.weapon_slots is not p2.weapon_slots
