"""
Action Phase: slot resolution, card resolution, last resorts, elusive cleanup.
"""

import pytest
from core.type import (
    PID, CardType, Slot, ActionField, Alignment, WeaponSlot, Role,
    Equip, Wield, Disarm, Resolve, Eat,
)
from core.engine import run, do
from combat import can_use_weapon
from cards import enemy, weapon, food, role_card
from phase.action import (
    action_phase, _resolve_slot,
    _legal_slot_choices, _action_play,
    _offer_last_resort, _run, _call_guards, _find_role_card,
    DISTANCE_PENALTY,
)
from phase.setup import create_initial_state
from helpers import interp, minimal_game, count_all_cards


# ── Helpers ───────────────────────────────────────────────────

def _armed(level, sharpness_level=0):
    ws = WeaponSlot()
    ws._weapon_slot.slot(weapon(level))
    if sharpness_level > 0:
        ws.killstack.slot(enemy(sharpness_level))
    return ws


# ── _is_first_slot ────────────────────────────────────────────

class TestIsFirstSlot:

    def test_empty_slot_not_first(self):
        assert not Slot().is_first

    def test_slot_with_non_first_card(self):
        e = enemy(3)
        s = Slot([e])
        assert not s.is_first

    def test_slot_with_first_card(self):
        from core.type import Card
        c = Card("first_enemy", "First Enemy", "", 5, (CardType.ENEMY,), False, True)
        s = Slot([c])
        assert s.is_first


# ── Resolve action: food ──────────────────────────────────────

class TestResolveFood:

    def test_food_heals_and_discards(self):
        g = minimal_game()
        g.players[PID.RED].hp = 10
        f = food(5)
        g.players[PID.RED].action_field.top_distant.slot(f)

        run(g, do(Resolve(PID.RED, f)), interp())
        assert g.players[PID.RED].hp == 15
        assert f in g.players[PID.RED].discard.cards
        assert g.players[PID.RED].is_satiated is True

    def test_second_food_no_heal(self):
        g = minimal_game()
        g.players[PID.RED].hp = 10
        g.players[PID.RED].is_satiated = True
        f = food(5)
        g.players[PID.RED].action_field.top_distant.slot(f)

        run(g, do(Resolve(PID.RED, f)), interp())
        assert g.players[PID.RED].hp == 10  # no heal
        assert f in g.players[PID.RED].discard.cards

    def test_food_heal_capped_at_ceiling(self):
        g = minimal_game()
        g.players[PID.RED].hp = 18
        g.players[PID.RED].hp_ceiling = 20
        f = food(5)
        g.players[PID.RED].action_field.top_distant.slot(f)

        run(g, do(Resolve(PID.RED, f)), interp())
        assert g.players[PID.RED].hp == 20  # capped at ceiling


# ── Eat action directly ──────────────────────────────────────

class TestEatAction:

    def test_eat_heals_and_satiates(self):
        g = minimal_game()
        g.players[PID.RED].hp = 10
        f = food(7)
        g.players[PID.RED].action_field.top_distant.slot(f)

        run(g, do(Eat(PID.RED, f)), interp())
        assert g.players[PID.RED].hp == 17
        assert g.players[PID.RED].is_satiated is True
        assert f in g.players[PID.RED].discard.cards

    def test_eat_when_satiated_only_discards(self):
        g = minimal_game()
        g.players[PID.RED].hp = 10
        g.players[PID.RED].is_satiated = True
        f = food(7)
        g.players[PID.RED].action_field.top_distant.slot(f)

        run(g, do(Eat(PID.RED, f)), interp())
        assert g.players[PID.RED].hp == 10
        assert f in g.players[PID.RED].discard.cards


# ── Resolve action: enemy ─────────────────────────────────────

class TestResolveEnemy:

    def test_enemy_combat_with_fists(self):
        g = minimal_game()
        e = enemy(5)
        g.players[PID.RED].action_field.top_distant.slot(e)

        # choice 0 = fists
        run(g, do(Resolve(PID.RED, e)), interp(0))
        assert g.players[PID.RED].hp == 15
        assert e in g.players[PID.RED].discard.cards

    def test_enemy_combat_with_weapon(self):
        g = minimal_game()
        e = enemy(5)
        g.players[PID.RED].action_field.top_distant.slot(e)
        g.players[PID.RED].weapon_slots = [_armed(5, sharpness_level=5)]

        # choice 1 = weapon; sharpness = min(5, 5) = 5, damage = 5-5 = 0
        run(g, do(Resolve(PID.RED, e)), interp(1))
        assert g.players[PID.RED].hp == 20
        ws = g.players[PID.RED].weapon_slots[0]
        assert e in ws.killstack.cards


# ── Resolve action: weapon ────────────────────────────────────

class TestResolveWeapon:

    def test_wield_weapon_from_action_field(self):
        g = minimal_game()
        w = weapon(6)
        g.players[PID.RED].action_field.top_distant.slot(w)

        run(g, do(Resolve(PID.RED, w)), interp())
        ws = g.players[PID.RED].weapon_slots[0]
        assert ws.weapon is w

    def test_wield_replaces_existing_weapon(self):
        g = minimal_game()
        old_w = weapon(3)
        new_w = weapon(7)
        ws = g.players[PID.RED].weapon_slots[0]
        ws._weapon_slot.slot(old_w)
        g.players[PID.RED].action_field.top_distant.slot(new_w)

        run(g, do(Resolve(PID.RED, new_w)), interp())
        assert ws.weapon is new_w
        assert old_w in g.players[PID.RED].discard.cards

    def test_wield_discards_kill_pile(self):
        g = minimal_game()
        old_w = weapon(3)
        kill1 = enemy(2)
        new_w = weapon(7)
        ws = g.players[PID.RED].weapon_slots[0]
        ws._weapon_slot.slot(old_w)
        ws.killstack.slot(kill1)
        g.players[PID.RED].action_field.top_distant.slot(new_w)

        run(g, do(Resolve(PID.RED, new_w)), interp())
        assert ws.weapon is new_w
        assert old_w in g.players[PID.RED].discard.cards
        assert kill1 in g.players[PID.RED].discard.cards
        assert ws.killstack.is_empty()

    def test_wield_prompts_for_weapon_slot_when_multiple(self):
        g = minimal_game()
        w1 = weapon(3)
        w2 = weapon(5)
        new_w = weapon(8)
        ws0, ws1 = WeaponSlot(), WeaponSlot()
        ws0._weapon_slot.slot(w1)
        ws1._weapon_slot.slot(w2)
        g.players[PID.RED].weapon_slots = [ws0, ws1]
        g.players[PID.RED].action_field.top_distant.slot(new_w)

        # choice 1 = second weapon slot
        run(g, do(Wield(PID.RED, new_w)), interp(1))
        assert ws1.weapon is new_w
        assert ws0.weapon is w1  # untouched
        assert w2 in g.players[PID.RED].discard.cards


# ── Resolve action: equipment ─────────────────────────────────

class TestResolveEquipment:

    def test_equip_into_empty_slot(self):
        g = minimal_game()
        from core.type import Card
        eq = Card("shield", "Shield", "", None, (CardType.EQUIPMENT,), False, False)
        g.players[PID.RED].action_field.top_distant.slot(eq)

        run(g, do(Resolve(PID.RED, eq)), interp())
        assert eq in g.players[PID.RED].equipment.cards

    def test_equip_overflow_discards_chosen(self):
        g = minimal_game()
        from core.type import Card
        eq1 = Card("helm", "Helm", "", None, (CardType.EQUIPMENT,), False, False)
        eq2 = Card("boots", "Boots", "", None, (CardType.EQUIPMENT,), False, False)
        eq3 = Card("ring", "Ring", "", None, (CardType.EQUIPMENT,), False, False)
        g.players[PID.RED].equipment.slot(eq1)
        g.players[PID.RED].equipment.slot(eq2)
        g.players[PID.RED].action_field.top_distant.slot(eq3)

        # Choice 0 = discard first listed equipment
        run(g, do(Resolve(PID.RED, eq3)), interp(0))
        assert eq3 in g.players[PID.RED].equipment.cards
        assert len(g.players[PID.RED].equipment.cards) == 2

    def test_equip_respects_max_equipment(self):
        """A lowered max_equipment forces discard even with only 1 equipped."""
        g = minimal_game()
        from core.type import Card
        eq1 = Card("helm", "Helm", "", None, (CardType.EQUIPMENT,), False, False)
        eq2 = Card("ring", "Ring", "", None, (CardType.EQUIPMENT,), False, False)
        g.players[PID.RED].max_equipment = 1
        g.players[PID.RED].equipment.slot(eq1)
        g.players[PID.RED].action_field.top_distant.slot(eq2)

        run(g, do(Resolve(PID.RED, eq2)), interp(0))
        assert eq2 in g.players[PID.RED].equipment.cards
        assert eq1 in g.players[PID.RED].discard.cards


# ── Disarm action ─────────────────────────────────────────────

class TestDisarm:

    def test_disarm_removes_weapon(self):
        g = minimal_game()
        w = weapon(5)
        ws = g.players[PID.RED].weapon_slots[0]
        ws._weapon_slot.slot(w)

        run(g, do(Disarm(PID.RED, "test")), interp())
        assert ws.weapon is None
        assert w in g.players[PID.RED].discard.cards

    def test_disarm_discards_kill_pile(self):
        g = minimal_game()
        w = weapon(5)
        k1, k2 = enemy(3), enemy(4)
        ws = g.players[PID.RED].weapon_slots[0]
        ws._weapon_slot.slot(w)
        ws.killstack.slot(k1)
        ws.killstack.slot(k2)

        run(g, do(Disarm(PID.RED, "test")), interp())
        assert ws.weapon is None
        assert ws.killstack.is_empty()
        assert w in g.players[PID.RED].discard.cards
        assert k1 in g.players[PID.RED].discard.cards
        assert k2 in g.players[PID.RED].discard.cards

    def test_disarm_noop_when_unarmed(self):
        g = minimal_game()
        ws = g.players[PID.RED].weapon_slots[0]
        assert ws.weapon is None

        run(g, do(Disarm(PID.RED, "test")), interp())
        assert ws.weapon is None

    def test_disarm_clears_all_weapon_slots(self):
        g = minimal_game()
        w1, w2 = weapon(3), weapon(5)
        ws0, ws1 = WeaponSlot(), WeaponSlot()
        ws0._weapon_slot.slot(w1)
        ws1._weapon_slot.slot(w2)
        g.players[PID.RED].weapon_slots = [ws0, ws1]

        run(g, do(Disarm(PID.RED, "test")), interp())
        assert ws0.weapon is None
        assert ws1.weapon is None
        assert w1 in g.players[PID.RED].discard.cards
        assert w2 in g.players[PID.RED].discard.cards


# ── _legal_slot_choices ───────────────────────────────────────

class TestLegalSlotChoices:

    def test_includes_own_nonempty_slots(self):
        g = minimal_game()
        e = enemy(3)
        g.players[PID.RED].action_field.top_distant.slot(e)

        choices = _legal_slot_choices(PID.RED, g)
        slots = [s for s, _, _, _ in choices]
        assert g.players[PID.RED].action_field.top_distant in slots

    def test_excludes_empty_slots(self):
        g = minimal_game()
        choices = _legal_slot_choices(PID.RED, g)
        assert len(choices) == 0

    def test_includes_opponent_slots(self):
        g = minimal_game()
        e = enemy(3)
        g.players[PID.BLUE].action_field.top_distant.slot(e)

        choices = _legal_slot_choices(PID.RED, g)
        opp_choices = [(s, l, o, d) for s, l, o, d in choices if o]
        assert len(opp_choices) == 1
        assert opp_choices[0][3] is True  # distant

    def test_first_slot_excluded_after_first_play(self):
        g = minimal_game()
        from core.type import Card
        first_card = Card("boss", "Boss", "", 10, (CardType.ENEMY,), False, True)
        g.players[PID.RED].action_field.top_distant.slot(first_card)

        # first_play_done=False → first slot OK
        g.players[PID.RED].first_play_done = False
        assert len(_legal_slot_choices(PID.RED, g)) == 1

        # first_play_done=True → first slot excluded
        g.players[PID.RED].first_play_done = True
        assert len(_legal_slot_choices(PID.RED, g)) == 0


# ── _action_play with opponent consent ────────────────────────

class TestActionPlayConsent:

    def test_opponent_distant_requires_consent_and_penalty(self):
        g = minimal_game()
        e = enemy(3)
        g.players[PID.BLUE].action_field.top_distant.slot(e)

        # RED picks slot 0 (opponent top distant), BLUE allows (0), RED fights with fists (0)
        run(g, _action_play(PID.RED), interp(0, 0, blue=[0]))
        assert g.players[PID.RED].hp == 20 - DISTANCE_PENALTY - 3

    def test_opponent_hidden_requires_consent_no_penalty(self):
        g = minimal_game()
        e = enemy(3)
        g.players[PID.BLUE].action_field.top_hidden.slot(e)

        # RED picks slot 0 (opponent top hidden), BLUE allows (0), RED fights with fists (0)
        run(g, _action_play(PID.RED), interp(0, 0, blue=[0]))
        assert g.players[PID.RED].hp == 20 - 3  # no distance penalty

    def test_consent_denied_forces_repick(self):
        g = minimal_game()
        e1 = enemy(3)
        e2 = enemy(1)
        g.players[PID.BLUE].action_field.top_distant.slot(e1)
        g.players[PID.RED].action_field.top_distant.slot(e2)

        # RED picks opponent slot (idx 1), BLUE denies (1), RED re-picks own slot (idx 0), fists (0)
        run(g, _action_play(PID.RED), interp(1, 0, 0, blue=[1]))
        assert g.players[PID.RED].hp == 20 - 1  # fought e2 with fists, no penalty


# ── _resolve_slot: while loop ─────────────────────────────────

class TestResolveSlot:

    def test_resolves_all_cards_in_order(self):
        g = minimal_game()
        f1 = food(3)
        f2 = food(5)
        slot = g.players[PID.RED].action_field.top_distant
        slot.slot(f1)
        slot.slot(f2)  # f2 is on top (index 0)
        g.players[PID.RED].hp = 10

        run(g, _resolve_slot(PID.RED, slot), interp())
        # f2 heals (first eat), f1 doesn't (already satiated)
        assert g.players[PID.RED].hp == 15  # 10 + 5
        assert f1 in g.players[PID.RED].discard.cards
        assert f2 in g.players[PID.RED].discard.cards
        assert slot.is_empty()

    def test_while_loop_handles_dynamic_cards(self):
        """Slot is drained by resolving top repeatedly, not by snapshot iteration."""
        g = minimal_game()
        slot = g.players[PID.RED].action_field.top_distant
        # Stack 3 foods
        for i in range(3):
            slot.slot(food(1))

        run(g, _resolve_slot(PID.RED, slot), interp())
        assert slot.is_empty()
        assert len(g.players[PID.RED].discard.cards) == 3


# ── Last resorts ──────────────────────────────────────────────

class TestFindRoleCard:

    def test_finds_good_role_card(self):
        g = minimal_game()
        rc = role_card(good=True)
        g.players[PID.RED].equipment.slot(rc)
        assert _find_role_card(g.players[PID.RED]) is rc

    def test_returns_none_when_no_role_card(self):
        g = minimal_game()
        assert _find_role_card(g.players[PID.RED]) is None


class TestOfferLastResort:

    def test_no_last_resort(self):
        g = minimal_game()
        e = enemy(3)
        g.players[PID.RED].action_field.top_distant.slot(e)

        # Choice 0 = "None"
        run(g, _offer_last_resort(PID.RED), interp(0))
        # Nothing changed — card still on field
        assert e in g.players[PID.RED].action_field.top_distant.cards


class TestRunLastResort:

    def test_run_refreshes_field_and_redeals(self):
        g = minimal_game()
        e1, e2 = enemy(3), enemy(5)
        g.players[PID.RED].action_field.top_distant.slot(e1)
        g.players[PID.RED].action_field.top_hidden.slot(e2)

        # Need 4 cards in RED's deck for the redeal (4 slots to fill)
        for i in range(4):
            g.players[PID.RED].deck.slot(enemy(i + 1))

        # BLUE keeps all 4 cards (choice 0 = Keep for each)
        run(g, _run(PID.RED), interp(blue=[0, 0, 0, 0]))

        # Old cards should be in refresh pile
        assert e1 in g.players[PID.RED].refresh.cards
        assert e2 in g.players[PID.RED].refresh.cards
        # 4 cards dealt to action field (all slots were empty after refresh)
        non_empty = [
            s for s in g.players[PID.RED].action_field.slots_in_fill_order()
            if not s.is_empty()
        ]
        assert len(non_empty) == 4

    def test_run_recycle_replaces_card(self):
        g = minimal_game()
        # 5 cards in deck: 4 for initial draw + 1 for recycle replacement
        for i in range(5):
            g.players[PID.RED].deck.slot(enemy(i + 1))

        # BLUE recycles first card (1), keeps rest (0,0,0)
        run(g, _run(PID.RED), interp(blue=[1, 0, 0, 0]))

        # 1 card recycled to refresh, 4 dealt to field
        assert len(g.players[PID.RED].refresh.cards) == 1
        non_empty = [
            s for s in g.players[PID.RED].action_field.slots_in_fill_order()
            if not s.is_empty()
        ]
        assert len(non_empty) == 4


class TestCallGuards:

    def test_call_guards_discards_role_and_disarms_and_deploys(self):
        g = minimal_game()
        from cards import guard
        rc = role_card(good=True)
        g.players[PID.RED].equipment.slot(rc)
        g.players[PID.RED].alignment = Alignment.GOOD

        opp_weapon = weapon(5)
        g.players[PID.BLUE].weapon_slots[0]._weapon_slot.slot(opp_weapon)

        # 4 guards in guard deck
        for _ in range(4):
            g.guard_deck.slot(guard(10))

        run(g, _call_guards(PID.RED), interp())

        # Role card discarded
        assert rc in g.players[PID.RED].discard.cards
        # Opponent disarmed
        assert g.players[PID.BLUE].weapon_slots[0].weapon is None
        assert opp_weapon in g.players[PID.BLUE].discard.cards
        # Guards on opponent's field
        for slot in g.players[PID.BLUE].action_field.slots_in_fill_order():
            assert not slot.is_empty()
            assert slot.cards[0].name.startswith("guard")


# ── Full action phase integration ─────────────────────────────

class TestActionPhaseIntegration:

    def test_three_plays_each_alternating(self):
        """Both players resolve 3 food cards each (priority=RED)."""
        g = minimal_game()
        g.priority = PID.RED

        # Fill each player's field with 3 foods, leave bottom_distant empty
        for pid in PID:
            af = g.players[pid].action_field
            af.top_distant.slot(food(1))
            af.top_hidden.slot(food(1))
            af.bottom_hidden.slot(food(1))

        # Each player picks slot 0 each time (no last resort choice first)
        # RED: no last resort (0), slot 0, slot 0, slot 0
        # BLUE: no last resort (0), slot 0, slot 0, slot 0
        run(g, action_phase(), interp(0, 0, 0, 0, blue=[0, 0, 0, 0]))

        # Each player's foods discarded
        for pid in PID:
            af = g.players[pid].action_field
            assert af.top_distant.is_empty()
            assert af.top_hidden.is_empty()
            assert af.bottom_hidden.is_empty()
            assert g.players[pid].action_plays_left == 0
            assert g.players[pid].first_play_done is True

    def test_death_ends_phase_immediately(self):
        """A lethal enemy kills the player mid-phase; phase ends."""
        g = minimal_game()
        g.priority = PID.RED
        g.players[PID.RED].hp = 5

        e = enemy(10)
        g.players[PID.RED].action_field.top_distant.slot(e)
        g.players[PID.RED].action_field.top_hidden.slot(food(3))
        g.players[PID.BLUE].action_field.top_distant.slot(food(1))

        # RED: no last resort (0), pick slot 0 (top distant), fists (0)
        run(g, action_phase(), interp(0, 0, 0))
        assert g.players[PID.RED].is_dead

    def test_elusive_refreshed_at_end(self):
        """Unresolved elusive cards on the action field are refreshed."""
        g = minimal_game()
        g.priority = PID.RED
        from core.type import Card
        elusive = Card("wisp", "Wisp", "", 1, (CardType.ENEMY,), True, False)

        # RED has 3 normal foods + 1 elusive enemy on bottom_distant
        af = g.players[PID.RED].action_field
        af.top_distant.slot(food(1))
        af.top_hidden.slot(food(1))
        af.bottom_hidden.slot(food(1))
        af.bottom_distant.slot(elusive)

        # BLUE has 3 foods
        bf = g.players[PID.BLUE].action_field
        bf.top_distant.slot(food(1))
        bf.top_hidden.slot(food(1))
        bf.bottom_hidden.slot(food(1))

        # No last resort for either; each resolves slots 0,1,2
        run(g, action_phase(), interp(0, 0, 0, 0, blue=[0, 0, 0, 0]))

        # Elusive card should be refreshed (moved to RED's refresh pile)
        assert elusive in g.players[PID.RED].refresh.cards
        assert af.bottom_distant.is_empty()

    def test_action_phase_resets_plays_to_three(self):
        """action_phase always resets action_plays_left to 3 at the start."""
        g = minimal_game()
        g.priority = PID.RED
        for pid in PID:
            g.players[pid].action_plays_left = 0  # pre-set to 0
            af = g.players[pid].action_field
            af.top_distant.slot(food(1))
            af.top_hidden.slot(food(1))
            af.bottom_hidden.slot(food(1))

        # Despite pre-setting to 0, both get 3 plays
        # no-LR(0) + 3x slot(0) per player
        run(g, action_phase(), interp(0, 0, 0, 0, blue=[0, 0, 0, 0]))
        for pid in PID:
            assert g.players[pid].action_plays_left == 0
            assert g.players[pid].action_field.top_distant.is_empty()
            assert g.players[pid].action_field.top_hidden.is_empty()
            assert g.players[pid].action_field.bottom_hidden.is_empty()


# ── _offer_last_resort via integration ────────────────────────

class TestOfferLastResortRun:
    """Choosing Run through _offer_last_resort actually refreshes the field."""

    def test_choosing_run_refreshes_action_field(self):
        g = minimal_game()
        e = enemy(3)
        g.players[PID.RED].action_field.top_distant.slot(e)
        # Need 4 cards in deck for redeal
        for i in range(4):
            g.players[PID.RED].deck.slot(enemy(i + 1))

        # Choice 1 = "Run"; BLUE keeps all 4
        run(g, _offer_last_resort(PID.RED), interp(1, blue=[0, 0, 0, 0]))

        # Original card refreshed
        assert e in g.players[PID.RED].refresh.cards
        # Field refilled
        non_empty = [
            s for s in g.players[PID.RED].action_field.slots_in_fill_order()
            if not s.is_empty()
        ]
        assert len(non_empty) == 4


class TestOfferLastResortGuards:
    """Choosing Guards through _offer_last_resort actually deploys guards."""

    def test_choosing_guards_deploys(self):
        from cards import guard
        g = minimal_game()
        rc = role_card(good=True)
        g.players[PID.RED].equipment.slot(rc)
        g.players[PID.RED].alignment = Alignment.GOOD
        for _ in range(4):
            g.guard_deck.slot(guard(10))

        # Options: ["None", "Run", "Call the Guards"]; choice 2 = Guards
        run(g, _offer_last_resort(PID.RED), interp(2))

        assert rc in g.players[PID.RED].discard.cards
        for slot in g.players[PID.BLUE].action_field.slots_in_fill_order():
            assert not slot.is_empty()

    def test_evil_player_cannot_call_guards(self):
        """Evil players don't get the Guards option even with a role card equipped.

        Kills and→or mutant: with or, an Evil player with a role card
        would get Guards offered. Choice index 2 is valid only if Guards exists.
        """
        g = minimal_game()
        rc = role_card(good=False)
        g.players[PID.RED].equipment.slot(rc)
        g.players[PID.RED].alignment = Alignment.EVIL
        g.players[PID.RED].role = Role("???", Alignment.EVIL)

        # Only ["None", "Run"] should exist — index 2 is out of bounds
        with pytest.raises(IndexError):
            run(g, _offer_last_resort(PID.RED), interp(2))

    def test_good_player_without_role_card_cannot_call_guards(self):
        """Good player who lost their role card can't call guards."""
        g = minimal_game()
        # No role card equipped
        g.players[PID.RED].alignment = Alignment.GOOD

        # Only ["None", "Run"]; pick 0 (None)
        run(g, _offer_last_resort(PID.RED), interp(0))
        for slot in g.players[PID.BLUE].action_field.slots_in_fill_order():
            assert slot.is_empty()


# ── _legal_slot_choices: First + break, is_distant ────────────

class TestLegalSlotChoicesAdvanced:

    def test_first_slot_then_normal_slot_returns_normal(self):
        """Kills continue→break mutant: First slot skipped, next slot still added."""
        g = minimal_game()
        from core.type import Card
        first_card = Card("boss", "Boss", "", 10, (CardType.ENEMY,), False, True)
        normal_card = enemy(3)
        g.players[PID.RED].action_field.top_distant.slot(first_card)
        g.players[PID.RED].action_field.top_hidden.slot(normal_card)
        g.players[PID.RED].first_play_done = True

        choices = _legal_slot_choices(PID.RED, g)
        # First slot excluded, but top_hidden should be included
        slots = [s for s, _, _, _ in choices]
        assert g.players[PID.RED].action_field.top_hidden in slots
        assert g.players[PID.RED].action_field.top_distant not in slots

    def test_own_slots_are_not_distant(self):
        """Kills (False,False)→(False,True) mutant for own slots."""
        g = minimal_game()
        g.players[PID.RED].action_field.top_distant.slot(enemy(1))

        choices = _legal_slot_choices(PID.RED, g)
        assert len(choices) == 1
        _, _, is_opp, is_dist = choices[0]
        assert is_opp is False
        assert is_dist is False

    def test_opponent_first_slot_available_on_first_play(self):
        """Kills and→or mutant: opponent First slots available before first_play_done."""
        g = minimal_game()
        from core.type import Card
        first_card = Card("boss", "Boss", "", 10, (CardType.ENEMY,), False, True)
        g.players[PID.BLUE].action_field.top_distant.slot(first_card)
        g.players[PID.RED].first_play_done = False

        choices = _legal_slot_choices(PID.RED, g)
        opp_choices = [c for c in choices if c[2]]
        assert len(opp_choices) == 1

    def test_opponent_first_slot_then_normal_not_broken(self):
        """Kills continue→break on opponent First-slot filter."""
        g = minimal_game()
        from core.type import Card
        first_card = Card("boss", "Boss", "", 10, (CardType.ENEMY,), False, True)
        g.players[PID.BLUE].action_field.top_distant.slot(first_card)
        g.players[PID.BLUE].action_field.top_hidden.slot(enemy(1))
        g.players[PID.RED].first_play_done = True

        choices = _legal_slot_choices(PID.RED, g)
        opp_choices = [c for c in choices if c[2]]
        # First distant excluded, but hidden should be included
        assert len(opp_choices) == 1
        assert opp_choices[0][0] is g.players[PID.BLUE].action_field.top_hidden


# ── _resolve_top_of_deck ──────────────────────────────────────

class TestResolveTopOfDeck:

    def test_resolves_food_from_deck(self):
        g = minimal_game()
        g.players[PID.RED].hp = 10
        f = food(5)
        g.players[PID.RED].deck.slot(f)

        from phase.action import _resolve_top_of_deck
        run(g, _resolve_top_of_deck(PID.RED), interp())

        assert g.players[PID.RED].hp == 15
        assert f in g.players[PID.RED].discard.cards

    def test_resolves_enemy_from_deck(self):
        g = minimal_game()
        e = enemy(3)
        g.players[PID.RED].deck.slot(e)

        from phase.action import _resolve_top_of_deck
        run(g, _resolve_top_of_deck(PID.RED), interp(0))  # fists

        assert g.players[PID.RED].hp == 17
        assert e in g.players[PID.RED].discard.cards

    def test_fallback_triggered_when_no_legal_slots(self):
        """Full integration: _action_play falls back to top-of-deck."""
        g = minimal_game()
        g.players[PID.RED].hp = 10
        # No cards on any action field — empty choices
        f = food(7)
        g.players[PID.RED].deck.slot(f)

        run(g, _action_play(PID.RED), interp())
        assert g.players[PID.RED].hp == 17
        assert f in g.players[PID.RED].discard.cards


# ── count_all_cards with weapons ──────────────────────────────

class TestCountAllCardsWithWeapons:

    def test_counts_wielded_weapon(self):
        g = minimal_game()
        w = weapon(5)
        g.players[PID.RED].weapon_slots[0]._weapon_slot.slot(w)
        assert count_all_cards(g) == 1

    def test_counts_weapon_and_kills(self):
        g = minimal_game()
        w = weapon(5)
        k = enemy(3)
        ws = g.players[PID.RED].weapon_slots[0]
        ws._weapon_slot.slot(w)
        ws.killstack.slot(k)
        assert count_all_cards(g) == 2
