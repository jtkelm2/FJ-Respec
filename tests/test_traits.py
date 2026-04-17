"""
Trait dispatch infrastructure: BEFORE / REPLACEMENT / AFTER triggers, the
predicate filter, slot-derived vs persistent traits, keyword factory methods,
and ordering prompts.
"""

from core.type import (
    PID, Card, CardType, Slot, SlotKind, Trait, TKind, TextOption,
    Heal, Damage, Action, GameState, Effect, Negotiation,
    Resolve, Discard, Slay, Slot2Slot, SlotCard,
    PromptHalf,
)
from core.engine import do
from interact.interpret import run, AggregateInterpreter
from interact.player import ScriptedPlayer
from helpers import interp, minimal_game, count_all_cards


class _RecordingPlayer(ScriptedPlayer):
    def __init__(self, script):
        super().__init__(script)
        self.prompts: list[PromptHalf] = []
    def prompt(self, prompt_half):
        self.prompts.append(prompt_half)
        return super().prompt(prompt_half)


def _interp_recording(*red_choices, blue=None):
    if blue is None: blue = []
    red_p = _RecordingPlayer(list(red_choices))
    blue_p = _RecordingPlayer(list(blue))
    return AggregateInterpreter(red_p, blue_p), red_p, blue_p


# --- Helpers -------------------------------------------------------------

def _log_cb(log, msg, side=None):
    """Callback that logs `msg`, then optionally runs `side` (Action -> Effect)."""
    def cb(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            log.append(msg)
            if side is not None:
                yield from side(a)(g)
        return eff
    return cb


def _logging_trait(name, kind, predicate, log, msg, side=None):
    """Convenience: a complete Trait with logging callback."""
    return Trait(name, kind, lambda a: predicate(a), _log_cb(log, msg, side))


# --- BEFORE --------------------------------------------------------------

class TestBeforeTrait:

    def test_fires_before_action_when_predicate_matches(self):
        g = minimal_game()
        log = []
        g.active_traits.append(
            _logging_trait("t", TKind.BEFORE,
                lambda a: isinstance(a, Heal) and a.target == PID.RED,
                log, "fired", lambda a: do(Damage(PID.BLUE, 1, "test"))))
        g.players[PID.RED].hp = 10
        g.players[PID.BLUE].hp = 10

        run(g, do(Heal(PID.RED, 5)), interp())

        assert log == ["fired"]
        assert g.players[PID.RED].hp == 15
        assert g.players[PID.BLUE].hp == 9

    def test_does_not_fire_when_predicate_misses(self):
        g = minimal_game()
        log = []
        g.active_traits.append(
            _logging_trait("t", TKind.BEFORE,
                lambda a: isinstance(a, Heal) and a.target == PID.RED,
                log, "fired", lambda a: do(Damage(PID.BLUE, 1, "test"))))
        g.players[PID.RED].hp = 10
        g.players[PID.BLUE].hp = 10

        run(g, do(Heal(PID.BLUE, 5)), interp())

        assert log == []
        assert g.players[PID.BLUE].hp == 15
        assert g.players[PID.RED].hp == 10


# --- AFTER ---------------------------------------------------------------

class TestAfterTrait:

    def test_fires_after_action_completes(self):
        g = minimal_game()
        observed_hp = []
        def side(a):
            def eff(g):
                observed_hp.append(g.players[PID.RED].hp)
                return; yield  # pragma: no cover
            return eff
        g.active_traits.append(
            _logging_trait("t", TKind.AFTER,
                lambda a: isinstance(a, Heal) and a.target == PID.RED,
                [], "fired", side))
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 5)), interp())

        assert observed_hp == [15]


# --- REPLACEMENT ---------------------------------------------------------

class TestReplacementTrait:

    def test_replaces_base_behavior(self):
        g = minimal_game()
        g.active_traits.append(
            Trait("t", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.RED,
                  lambda a: do(Damage(PID.RED, a.amount, "flip"))))
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 3)), interp())

        assert g.players[PID.RED].hp == 7

    def test_two_candidates_prompt_target_player(self):
        g = minimal_game()
        g.active_traits.append(
            Trait("damage_3", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.RED,
                  lambda a: do(Damage(PID.RED, 3, "r1"))))
        g.active_traits.append(
            Trait("damage_7", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.RED,
                  lambda a: do(Damage(PID.RED, 7, "r2"))))
        g.players[PID.RED].hp = 20

        run(g, do(Heal(PID.RED, 1)), interp(TextOption("damage_7")))

        assert g.players[PID.RED].hp == 13

    def test_predicate_misses_means_no_replacement(self):
        g = minimal_game()
        g.active_traits.append(
            Trait("t", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.RED,
                  lambda a: do(Damage(PID.RED, 99, "flip"))))
        g.players[PID.BLUE].hp = 10

        run(g, do(Heal(PID.BLUE, 4)), interp())

        assert g.players[PID.BLUE].hp == 14


# --- AFTER ordering -------------------------------------------------------

class TestAfterOrderingPrompt:

    def test_two_after_traits_prompt_for_first(self):
        g = minimal_game()
        log = []
        for nm in ("a1", "a2"):
            g.active_traits.append(
                _logging_trait(nm, TKind.AFTER,
                    lambda a: isinstance(a, Heal) and a.target == PID.RED,
                    log, nm))
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 1)), interp(TextOption("a2")))

        assert log == ["a2", "a1"]


# --- Slot-derived: WHILE_EQUIPPED ----------------------------------------

class TestWhileEquippedKeyword:

    def test_fires_while_in_equipment(self):
        g = minimal_game()
        log = []
        c = Card("synth_eq", "SynthEq", "", None, (CardType.EQUIPMENT,),
                 False, False)
        c.traits = [Trait.while_equipped(c, TKind.AFTER,
            lambda a: isinstance(a, Heal) and a.target == PID.RED,
            _log_cb(log, "fired"))]
        g.players[PID.RED].equipment.slot(c)
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 1)), interp())

        assert log == ["fired"]

    def test_silent_when_card_not_in_equipment(self):
        g = minimal_game()
        log = []
        c = Card("synth_eq", "SynthEq", "", None, (CardType.EQUIPMENT,),
                 False, False)
        c.traits = [Trait.while_equipped(c, TKind.AFTER,
            lambda a: isinstance(a, Heal) and a.target == PID.RED,
            _log_cb(log, "fired"))]
        g.players[PID.RED].discard.slot(c)
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 1)), interp())

        assert log == []

    def test_silent_when_card_in_action_field(self):
        g = minimal_game()
        log = []
        c = Card("synth_eq", "SynthEq", "", None, (CardType.EQUIPMENT,),
                 False, False)
        c.traits = [Trait.while_equipped(c, TKind.AFTER,
            lambda a: isinstance(a, Heal),
            _log_cb(log, "fired"))]
        g.players[PID.RED].action_field.top_distant.slot(c)
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 1)), interp())

        assert log == []


# --- Persistent traits (GameState.active_traits) -------------------------

class TestPersistentTrait:

    def test_active_traits_fire_with_no_card_anywhere(self):
        g = minimal_game()
        log = []
        g.active_traits.append(
            _logging_trait("t", TKind.AFTER,
                lambda a: isinstance(a, Heal) and a.target == PID.BLUE,
                log, "fired"))
        g.players[PID.BLUE].hp = 10

        run(g, do(Heal(PID.BLUE, 1)), interp())

        assert log == ["fired"]


# --- AS_A_WEAPON keyword -------------------------------------------------

class TestAsAWeaponKeyword:

    def test_fires_while_wielded(self):
        g = minimal_game()
        log = []
        c = Card("synth_w", "SynthW", "", 1, (CardType.WEAPON,), False, False)
        c.traits = [Trait.as_a_weapon(c, TKind.AFTER,
            lambda a: isinstance(a, Heal) and a.target == PID.RED,
            _log_cb(log, "fired"))]
        g.players[PID.RED].weapon_slots[0].wield(c)
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 1)), interp())

        assert log == ["fired"]

    def test_silent_when_in_equipment_not_wielded(self):
        g = minimal_game()
        log = []
        c = Card("synth_w", "SynthW", "", None, (CardType.EQUIPMENT,),
                 False, False)
        c.traits = [Trait.as_a_weapon(c, TKind.AFTER,
            lambda a: isinstance(a, Heal) and a.target == PID.RED,
            _log_cb(log, "fired"))]
        g.players[PID.RED].equipment.slot(c)
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 1)), interp())

        assert log == []


# --- ON_DISCARD keyword ---------------------------------------------------

class TestOnDiscardKeyword:

    def test_fires_on_self_discard(self):
        g = minimal_game()
        log = []
        c = Card("synth_d", "SynthD", "", None, (CardType.EQUIPMENT,),
                 False, False)
        c.traits = [Trait.on_discard(c, _log_cb(log, "fired"))]
        g.players[PID.RED].equipment.slot(c)

        run(g, do(Discard(PID.RED, c, "test")), interp())

        assert log == ["fired"]
        assert c in g.players[PID.RED].discard.cards

    def test_silent_on_other_card_discard(self):
        g = minimal_game()
        log = []
        c = Card("synth_d", "SynthD", "", None, (CardType.EQUIPMENT,),
                 False, False)
        other_c = Card("other", "Other", "", None, (CardType.EQUIPMENT,),
                       False, False)
        c.traits = [Trait.on_discard(c, _log_cb(log, "fired"))]
        g.players[PID.RED].equipment.slot(c)
        g.players[PID.RED].hand.slot(other_c)

        run(g, do(Discard(PID.RED, other_c, "test")), interp())

        assert log == []


# --- ON_KILL keyword ------------------------------------------------------

class TestOnKillKeyword:

    def test_fires_on_slay_with_weapon(self):
        g = minimal_game()
        log = []
        en = Card("synth_e", "SynthE", "", 3, (CardType.ENEMY,), False, False)
        en.traits = [Trait.on_kill(en, _log_cb(log, "fired"))]
        g.players[PID.RED].action_field.top_distant.slot(en)
        ws = g.players[PID.RED].weapon_slots[0]

        run(g, do(Slay(PID.RED, en, ws, "test")), interp())

        assert log == ["fired"]

    def test_fires_on_slay_with_fists(self):
        g = minimal_game()
        log = []
        en = Card("synth_e", "SynthE", "", 3, (CardType.ENEMY,), False, False)
        en.traits = [Trait.on_kill(en, _log_cb(log, "fired"))]
        g.players[PID.RED].action_field.top_distant.slot(en)

        run(g, do(Slay(PID.RED, en, None, "test")), interp())

        assert log == ["fired"]


# --- ON_PLACEMENT keyword -------------------------------------------------

class TestOnPlacementKeyword:

    def test_fires_on_placement_into_action_field(self):
        g = minimal_game()
        log = []
        af_slot = g.players[PID.RED].action_field.top_distant
        c = Card("synth_p", "SynthP", "", 1, (CardType.ENEMY,), False, False)
        c.traits = [Trait.on_placement(c, _log_cb(log, "fired"))]
        g.players[PID.RED].deck.slot(c)

        run(g, do(Slot2Slot(g.players[PID.RED].deck, af_slot, "test")), interp())

        assert log == ["fired"]


# --- AFTER_DEATH keyword --------------------------------------------------

class TestAfterDeathKeyword:

    def test_installs_permanent_trait_on_discard(self):
        g = minimal_game()
        log = []
        permanent = _logging_trait("perm", TKind.AFTER,
            lambda a: isinstance(a, Heal), log, "permanent_fired")
        en = Card("synth_ad", "SynthAd", "", 5, (CardType.ENEMY,), False, False)
        en.traits = [Trait.after_death(en, permanent)]
        g.players[PID.RED].action_field.top_distant.slot(en)

        assert len(g.active_traits) == 0
        run(g, do(Discard(PID.RED, en, "test")), interp())
        assert len(g.active_traits) == 1

        g.players[PID.RED].hp = 10
        run(g, do(Heal(PID.RED, 1)), interp())
        assert log == ["permanent_fired"]

    def test_silent_while_on_action_field(self):
        g = minimal_game()
        permanent = _logging_trait("perm", TKind.AFTER,
            lambda a: True, [], "should_not_fire")
        en = Card("synth_ad", "SynthAd", "", 1, (CardType.ENEMY,), False, False)
        en.traits = [Trait.after_death(en, permanent)]
        g.players[PID.RED].action_field.top_distant.slot(en)
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 1)), interp())

        assert len(g.active_traits) == 0


# --- Multi-trait: continue not break --------------------------------------

class TestMultiTraitContinueNotBreak:

    def test_second_trait_fires_when_first_keyword_fails(self):
        g = minimal_game()
        log = []
        c = Card("synth_multi", "SynthMulti", "", None, (CardType.EVENT,),
                 False, False)
        t_eq = Trait.while_equipped(c, TKind.AFTER,
            lambda a: True, _log_cb(log, "eq_fired"))
        t_resolve = Trait.on_resolve(c, _log_cb(log, "resolve_fired"))
        c.traits = [t_eq, t_resolve]
        g.players[PID.RED].action_field.top_distant.slot(c)

        run(g, do(Resolve(PID.RED, c, "test")), interp())

        assert "resolve_fired" in log
        assert "eq_fired" not in log


# --- Chooser tests --------------------------------------------------------

class TestAfterOrderingChooserIsPriorityForNonHpAction:

    def test_priority_orders_discard(self):
        g = minimal_game()
        log = []
        c = Card("synth_x", "SynthX", "", None, (CardType.EQUIPMENT,),
                 False, False)
        g.players[PID.RED].equipment.slot(c)
        for nm in ("alpha", "beta"):
            g.active_traits.append(
                Trait(nm, TKind.AFTER,
                      lambda a, n=nm: isinstance(a, Discard) and a.card is c,
                      _log_cb(log, nm)))
        run(g, do(Discard(PID.RED, c, "test")), interp(TextOption("beta")))

        assert log == ["beta", "alpha"]


class TestAfterOrderingChooserIsTarget:

    def test_blue_target_orders_blue_response(self):
        g = minimal_game()
        log = []
        for nm in ("first", "second"):
            g.active_traits.append(
                _logging_trait(nm, TKind.AFTER,
                    lambda a: isinstance(a, Heal) and a.target == PID.BLUE,
                    log, nm))
        g.players[PID.BLUE].hp = 10

        run(g, do(Heal(PID.BLUE, 1)), interp(blue=[TextOption("second")]))

        assert log == ["second", "first"]


class TestReplacementChooserIsTarget:

    def test_blue_target_chooses_blue_response(self):
        g = minimal_game()
        g.active_traits.append(
            Trait("d3", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.BLUE,
                  lambda a: do(Damage(PID.BLUE, 3, "r1"))))
        g.active_traits.append(
            Trait("d7", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.BLUE,
                  lambda a: do(Damage(PID.BLUE, 7, "r2"))))
        g.players[PID.BLUE].hp = 20

        run(g, do(Heal(PID.BLUE, 1)), interp(blue=[TextOption("d7")]))

        assert g.players[PID.BLUE].hp == 13


# --- Prompt content validation --------------------------------------------

class TestPromptOptionsRecorded:

    def test_replacement_prompt_lists_trait_names(self):
        g = minimal_game()
        g.active_traits.append(
            Trait("alpha", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.RED,
                  lambda a: do(Damage(PID.RED, 1, "a"))))
        g.active_traits.append(
            Trait("beta", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.RED,
                  lambda a: do(Damage(PID.RED, 1, "b"))))
        g.players[PID.RED].hp = 10

        i, red_p, _ = _interp_recording(TextOption("alpha"))
        run(g, do(Heal(PID.RED, 1)), i)

        assert len(red_p.prompts) == 1
        opts = red_p.prompts[0].options
        assert TextOption("alpha") in opts
        assert TextOption("beta") in opts

    def test_after_ordering_prompt_lists_trait_names(self):
        g = minimal_game()
        log = []
        for nm in ("p1", "p2"):
            g.active_traits.append(
                _logging_trait(nm, TKind.AFTER,
                    lambda a: isinstance(a, Heal) and a.target == PID.RED,
                    log, nm))
        g.players[PID.RED].hp = 10

        i, red_p, _ = _interp_recording(TextOption("p2"))
        run(g, do(Heal(PID.RED, 1)), i)

        assert len(red_p.prompts) == 1
        opts = red_p.prompts[0].options
        assert TextOption("p1") in opts
        assert TextOption("p2") in opts


# --- Conservation invariant -----------------------------------------------

class TestConservation:

    def test_card_count_preserved_across_replacement(self):
        g = minimal_game()
        c1 = Card("c1", "C1", "", 1, (CardType.FOOD,), False, False)
        c2 = Card("c2", "C2", "", 2, (CardType.FOOD,), False, False)
        g.players[PID.RED].deck.slot(c1)
        g.players[PID.BLUE].deck.slot(c2)
        before = count_all_cards(g)

        g.active_traits.append(
            Trait("flip", TKind.REPLACEMENT,
                  lambda a: isinstance(a, Heal) and a.target == PID.RED,
                  lambda a: do(Damage(PID.RED, 1, "flip"))))
        g.players[PID.RED].hp = 10

        run(g, do(Heal(PID.RED, 5)), interp())

        assert count_all_cards(g) == before
