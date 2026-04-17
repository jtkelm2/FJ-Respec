"""
Modifier / query system: INTERCEPT and MUTATE modifiers on computed values,
plus end-to-end tests for The Emperor and Gobshite.
"""

from core.type import (
    PID, Card, CardType, Slot, SlotKind, Modifier, MKind, TextOption,
    Sharpness, EnemyLevel, Query, Trait, TKind,
    Heal, Damage, Slay, Resolve, Discard,
    Action, Effect, GameState, Negotiation,
    WeaponSlot, PromptHalf, SlotOption, WeaponSlotOption,
)
from core.engine import do, query
from interact.interpret import run
from helpers import interp, minimal_game, count_all_cards
from cards import weapon, enemy, the_emperor, food
from cards.enemies import enemy_1


# --- query() basics -------------------------------------------------------

class TestQueryBase:

    def test_no_modifiers_returns_base(self):
        g = minimal_game()
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(5))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, Sharpness(ws, PID.RED))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 5

    def test_enemy_level_no_modifiers(self):
        g = minimal_game()
        en = enemy(7)
        g.players[PID.RED].action_field.top_distant.slot(en)

        result = [None]
        def eff(g):
            result[0] = yield from query(g, EnemyLevel(en, None))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 7


# --- MUTATE modifier ------------------------------------------------------

class TestMutateModifier:

    def test_single_mutate_adjusts_value(self):
        g = minimal_game()
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(4))
        g.active_modifiers.append(
            Modifier("bonus", MKind.MUTATE,
                     lambda q: isinstance(q, Sharpness),
                     lambda q, v: v + 2))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, Sharpness(ws, PID.RED))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 6

    def test_two_mutates_compound(self):
        g = minimal_game()
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(3))
        g.active_modifiers.append(
            Modifier("plus1", MKind.MUTATE,
                     lambda q: isinstance(q, Sharpness),
                     lambda q, v: v + 1))
        g.active_modifiers.append(
            Modifier("plus2", MKind.MUTATE,
                     lambda q: isinstance(q, Sharpness),
                     lambda q, v: v + 2))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, Sharpness(ws, PID.RED))
        run(g, lambda g: eff(g), interp(TextOption("plus1")))

        assert result[0] == 6

    def test_predicate_misses_means_no_modification(self):
        g = minimal_game()
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(4))
        g.active_modifiers.append(
            Modifier("wrong", MKind.MUTATE,
                     lambda q: isinstance(q, EnemyLevel),
                     lambda q, v: v + 99))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, Sharpness(ws, PID.RED))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 4


# --- INTERCEPT modifier ---------------------------------------------------

class TestInterceptModifier:

    def test_intercept_replaces_value(self):
        g = minimal_game()
        en = enemy(3)
        g.players[PID.RED].action_field.top_distant.slot(en)
        g.active_modifiers.append(
            Modifier("override", MKind.INTERCEPT,
                     lambda q: isinstance(q, EnemyLevel) and q.enemy is en,
                     lambda q, v: 99))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, EnemyLevel(en, None))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 99

    def test_intercept_blocks_mutates(self):
        """When an INTERCEPT fires, MUTATEs are skipped entirely."""
        g = minimal_game()
        en = enemy(3)
        g.players[PID.RED].action_field.top_distant.slot(en)
        g.active_modifiers.append(
            Modifier("intercept", MKind.INTERCEPT,
                     lambda q: isinstance(q, EnemyLevel),
                     lambda q, v: 50))
        g.active_modifiers.append(
            Modifier("mutate", MKind.MUTATE,
                     lambda q: isinstance(q, EnemyLevel),
                     lambda q, v: v + 100))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, EnemyLevel(en, None))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 50

    def test_two_intercepts_prompt(self):
        g = minimal_game()
        en = enemy(3)
        g.players[PID.RED].action_field.top_distant.slot(en)
        g.active_modifiers.append(
            Modifier("alpha", MKind.INTERCEPT,
                     lambda q: isinstance(q, EnemyLevel),
                     lambda q, v: 10))
        g.active_modifiers.append(
            Modifier("beta", MKind.INTERCEPT,
                     lambda q: isinstance(q, EnemyLevel),
                     lambda q, v: 20))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, EnemyLevel(en, None))
        run(g, lambda g: eff(g), interp(TextOption("beta")))

        assert result[0] == 20


# --- The Emperor (while equipped, +1 sharpness) --------------------------

class TestTheEmperor:

    def test_adds_one_to_sharpness(self):
        g = minimal_game()
        emp = the_emperor()
        g.players[PID.RED].equipment.slot(emp)
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(4))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, Sharpness(ws, PID.RED))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 5

    def test_does_not_affect_other_player(self):
        g = minimal_game()
        emp = the_emperor()
        g.players[PID.RED].equipment.slot(emp)
        ws_blue = g.players[PID.BLUE].weapon_slots[0]
        ws_blue.wield(weapon(4))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, Sharpness(ws_blue, PID.BLUE))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 4

    def test_inactive_when_not_in_equipment(self):
        g = minimal_game()
        emp = the_emperor()
        g.players[PID.RED].discard.slot(emp)
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(4))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, Sharpness(ws, PID.RED))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 4

    def test_combat_damage_reduced(self):
        """End-to-end: Emperor equipped, fight an enemy — damage reduced by 1."""
        g = minimal_game()
        emp = the_emperor()
        g.players[PID.RED].equipment.slot(emp)
        w = weapon(3)
        g.players[PID.RED].weapon_slots[0].wield(w)
        en = enemy(5)
        g.players[PID.RED].action_field.top_distant.slot(en)
        g.players[PID.RED].hp = 20

        run(g, do(Resolve(PID.RED, en)), interp(WeaponSlotOption(g.players[PID.RED].weapon_slots[0])))

        # Effective sharpness = 3 + 1 = 4. Enemy level 5. Damage = 5 - 4 = 1.
        assert g.players[PID.RED].hp == 19


# --- Gobshite (enemy_1, level 22 with fists) -----------------------------

class TestGobshite:

    def test_level_22_with_fists(self):
        g = minimal_game()
        gob = enemy_1()
        g.players[PID.RED].action_field.top_distant.slot(gob)

        result = [None]
        def eff(g):
            result[0] = yield from query(g, EnemyLevel(gob, None))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 22

    def test_level_1_with_weapon(self):
        g = minimal_game()
        gob = enemy_1()
        g.players[PID.RED].action_field.top_distant.slot(gob)
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(5))

        result = [None]
        def eff(g):
            result[0] = yield from query(g, EnemyLevel(gob, ws))
        run(g, lambda g: eff(g), interp())

        assert result[0] == 1

    def test_fists_combat_deals_22_damage(self):
        """End-to-end: Gobshite with fists → 22 damage."""
        g = minimal_game()
        gob = enemy_1()
        g.players[PID.RED].action_field.top_distant.slot(gob)
        g.players[PID.RED].hp = 20
        before = count_all_cards(g)

        run(g, do(Resolve(PID.RED, gob)),
            interp(SlotOption(g.players[PID.RED].discard)))

        # 22 damage kills (HP 20 - 22 → dead)
        assert g.players[PID.RED].is_dead

    def test_weapon_combat_deals_normal_damage(self):
        """End-to-end: Gobshite with weapon → uses base level 1."""
        g = minimal_game()
        gob = enemy_1()
        g.players[PID.RED].action_field.top_distant.slot(gob)
        ws = g.players[PID.RED].weapon_slots[0]
        ws.wield(weapon(5))
        g.players[PID.RED].hp = 20

        run(g, do(Resolve(PID.RED, gob)),
            interp(WeaponSlotOption(ws)))

        # Sharpness 5, enemy level 1. Damage = max(0, 1 - 5) = 0.
        assert g.players[PID.RED].hp == 20
