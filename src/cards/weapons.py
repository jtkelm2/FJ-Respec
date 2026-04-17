from core.type import (
    Card, CardType, Trait, TKind, PID, other, SlotKind,
    Action, Discard, Damage, Slay, Wield, Refresh, SlotCard, DistancePenalty,
    AddCounter, EndActionPhase,
    Effect, GameState, Negotiation,
    PromptBuilder, TextOption, CardOption,
)
from core.engine import do


def weapon(level: int) -> Card:
    return Card(f"weapon_{level}", f"Weapon ({level})", "", level, (CardType.WEAPON,), False, False)  # pragma: no mutate


# weapon_1 (Fetch Stick) — As a weapon: If this has no counters, then when
# this would be discarded, instead the other player must wield it and add
# a counter to it.

def weapon_1() -> Card:
    card = Card(
        "weapon_1", "Fetch Stick (1)",  # pragma: no mutate
        "As a weapon: If this has no counters, then when this would be discarded, "  # pragma: no mutate
        "instead the other player must wield it and add a counter to it.",  # pragma: no mutate
        1, (CardType.WEAPON,), False, False,
    )
    def discard_cb(a: Action) -> Effect:
        assert isinstance(a, Discard)
        def eff(g: GameState) -> Negotiation:
            if card.counters == 0 and card.slot is not None and card.slot.kind == SlotKind.WEAPON:
                yield from do(AddCounter(card, "Fetch Stick"))(g)  # pragma: no mutate
                yield from do(Wield(other(a.discarder), card, "Fetch Stick"))(g)  # pragma: no mutate
            else:
                yield from do(Discard(a.discarder, card, "Fetch Stick normal"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_discard(card, discard_cb).instead()]
    return card


# weapon_3 (Piñata Stick) — On discard: You may deal 3 damage to the other
# player in order to see their hand.

def weapon_3() -> Card:
    card = Card(
        "weapon_3", "Piñata Stick (3)",  # pragma: no mutate
        "On discard: You may deal 3 damage to the other player in order to see their hand.",  # pragma: no mutate
        3, (CardType.WEAPON,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Discard)
        discarder = a.discarder
        def eff(g: GameState) -> Negotiation:
            opp = other(discarder)
            pb = (PromptBuilder("Piñata Stick: deal 3 damage to see opponent's hand?")  # pragma: no mutate
                  .add(TextOption("Yes"))  # pragma: no mutate
                  .add(TextOption("No")))  # pragma: no mutate
            response = yield pb.build(discarder)
            if response[discarder] == TextOption("Yes"):
                yield from do(Damage(opp, 3, "Piñata Stick"))(g)  # pragma: no mutate
                opp_hand = g.players[opp].hand.cards
                pb2 = PromptBuilder("Opponent's hand:")  # pragma: no mutate
                for c in opp_hand:
                    pb2.context(CardOption(c))
                pb2.add(TextOption("OK"))  # pragma: no mutate
                yield pb2.build(discarder)
        return eff
    card.traits = [Trait.on_discard(card, callback)]
    return card


# weapon_7 — As a weapon: You never pay the distance penalty. Whenever you
# kill an enemy on the other players field with this, discard the enemy.

def weapon_7() -> Card:
    card = Card(
        "weapon_7", "Weapon (7)",  # pragma: no mutate
        "As a weapon: You never pay the distance penalty. Whenever you kill an "  # pragma: no mutate
        "enemy on the other players field with this, discard the enemy.",  # pragma: no mutate
        7, (CardType.WEAPON,), False, False,
    )
    # No distance penalty: REPLACEMENT on DistancePenalty → no-op
    def no_penalty(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            return; yield  # pragma: no cover
        return eff

    # On-kill on opponent field: discard enemy instead of killstack
    def opp_field_discard(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            opp = other(a.slayer)
            enemy_slot = a.enemy.slot
            on_opp_field = (enemy_slot is not None
                            and enemy_slot in g.players[opp].action_field.slots_in_fill_order())
            if on_opp_field:
                yield from do(Discard(a.slayer, a.enemy, "weapon_7"))(g)  # pragma: no mutate
            else:
                yield from do(SlotCard(a.enemy, a.ws.killstack, "slay"))(g)  # pragma: no mutate
        return eff

    card.traits = [
        Trait.as_a_weapon(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, DistancePenalty),
            no_penalty),
        Trait.as_a_weapon(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Slay) and a.ws is not None and a.ws.weapon is card,
            opp_field_discard),
    ]
    return card


# weapon_10 (Vorpal Blade) — As a weapon: When this is discarded, place all
# your action cards into refresh. Your Action Phase is over.

def weapon_10() -> Card:
    card = Card(
        "weapon_10", "Vorpal Blade (10)",  # pragma: no mutate
        "As a weapon: When this is discarded, place all your action cards into "  # pragma: no mutate
        "refresh. Your Action Phase is over.",  # pragma: no mutate
        10, (CardType.WEAPON,), False, False,
    )
    def discard_cb(a: Action) -> Effect:
        assert isinstance(a, Discard)
        def eff(g: GameState) -> Negotiation:
            pid = a.discarder
            p = g.players[pid]
            for slot in p.action_field.slots_in_fill_order():
                for c in list(slot.cards):
                    yield from do(Refresh(c, pid, "Vorpal Blade"))(g)  # pragma: no mutate
            yield from do(EndActionPhase(pid, "Vorpal Blade"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_discard(card, discard_cb)]
    return card
