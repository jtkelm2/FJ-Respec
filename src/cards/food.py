from core.type import (
    Card, CardType, Slay, Trait, TKind, PID, Phase,
    Action, Eat, Damage, Heal, Discard, Equip, Wield,
    Resolve, EndPhase, AddCounter,
    Effect, GameState, Negotiation,
    PromptBuilder, TextOption,
)
from core.engine import do




def food(level: int) -> Card:
    return Card(f"food_{level}", f"Food ({level})", "", level, (CardType.FOOD,), False, False)  # pragma: no mutate


# food_1 — On resolve: After eating, receive d10 damage.

def food_1() -> Card:
    card = Card(
        "food_1", "Food? (5)",  # pragma: no mutate
        "On resolve: After eating, receive d10 damage.",  # pragma: no mutate
        5, (CardType.FOOD,),
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            yield from do(Eat(resolver, card, "food_1"))(g)  # pragma: no mutate
            if g.players[resolver].is_dead: return
            dmg = g.rng.randint(1, 10)
            yield from do(Damage(resolver, dmg, "food_1"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_resolve(card, callback).instead()]
    return card


# food_3 (Saltine Shuriken) — On resolve: You may wield this as a weapon
# instead of eating it. As a weapon: Discard all slain enemies. When this
# is discarded, you may eat this.

def food_3() -> Card:
    card = Card(
        "food_3", "Saltine Shuriken (3)",  # pragma: no mutate
        "On resolve: You may wield this as a weapon instead of eating it.\n"  # pragma: no mutate
        "As a weapon: Discard all slain enemies. When this is discarded, you may eat this.",  # pragma: no mutate
        3, (CardType.FOOD,), False, False,
    )
    # ON_RESOLVE: offer wield instead of eat
    def resolve_cb(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            pb = (PromptBuilder("Saltine Shuriken: Wield as weapon or eat?")  # pragma: no mutate
                  .add(TextOption("Eat"))  # pragma: no mutate
                  .add(TextOption("Wield")))  # pragma: no mutate
            response = yield pb.build(resolver)
            if response[resolver] == TextOption("Wield"):
                yield from do(Wield(resolver, card, "Saltine Shuriken"))(g)  # pragma: no mutate
            else:
                yield from do(Eat(resolver, card, "Saltine Shuriken"))(g)  # pragma: no mutate
        return eff

    # AS_A_WEAPON: on-kill discard the enemy (instead of killstack)
    def kill_cb(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            yield from do(Discard(a.slayer, a.enemy, "Saltine Shuriken"))(g)  # pragma: no mutate
        return eff
    
    def offer_to_eat(a: Action) -> Effect:
        assert isinstance(a, Discard)
        discarder = a.discarder
        def eff(g: GameState) -> Negotiation:
            pb = (PromptBuilder("Eat Saltine Shuriken?")  # pragma: no mutate
                  .add(TextOption("Yes"))  # pragma: no mutate
                  .add(TextOption("No")))  # pragma: no mutate
            response = yield pb.build(discarder)
            if response[discarder] == TextOption("Yes"):
                yield from do(Eat(discarder, card, "Saltine Shuriken eat"))(g)  # pragma: no mutate
            else:
                a.source = "Saltine Shuriken eating declined" # TODO: Sources need to be additive, not replacing
                yield from do(a)(g)
        return eff

    card.traits = [
        Trait.on_resolve(card, resolve_cb).instead(),
        Trait.as_a_weapon(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Slay) and a.ws is not None and a.ws.weapon is card,
            kill_cb),
        Trait.as_a_weapon(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Discard) and a.card is card and card.slot is not None and card.slot.owner is a.discarder and a.source != "food consumed",
            offer_to_eat)
    ]

    return card


# food_7 (Fat Sandwich) — On resolve: Equip this instead of eating it.
# While equipped: You may discard this to eat this.

def food_7() -> Card:
    card = Card(
        "food_7", "Fat Sandwich (7)",  # pragma: no mutate
        "On resolve: Equip this instead of eating it.\n"  # pragma: no mutate
        "While equipped: You may discard this to eat this.",  # pragma: no mutate
        7, (CardType.EQUIPMENT,), False, False,
    )
    
    def _eat_this(_:Action) -> Effect:
        def eff(g:GameState):
            assert card.slot is not None and card.slot.owner is not None
            owner = card.slot.owner
            yield from do(Eat(owner, card, "Eaten on discard (Fat Sandwich)"))(g)
        return eff

    card.traits = [Trait.while_equipped(card, TKind.REPLACEMENT,
                                        lambda a: isinstance(a, Discard) and a.card is card,
                                        _eat_this)]
    return card


# food_9 (Bellyfiller) — On resolve: Equip this instead of eating it.
# While equipped: At the end of each Refresh Phase, heal 3 HP then place
# a counter on this. If this has three counters on it, discard this.

def food_9() -> Card:
    card = Card(
        "food_9", "Bellyfiller",  # pragma: no mutate
        "On resolve: Equip this instead of eating it.\n"  # pragma: no mutate
        "While equipped: At the end of each Refresh Phase, heal 3 HP then "  # pragma: no mutate
        "place a counter on this. If this has three counters on it, discard this.",  # pragma: no mutate
        None, (CardType.FOOD,), False, False,
    )
    # ON_RESOLVE REPLACEMENT: equip instead of eat
    def resolve_cb(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        def eff(g: GameState) -> Negotiation:
            yield from do(Equip(a.resolver, card, "Bellyfiller"))(g)  # pragma: no mutate
        return eff

    # WHILE_EQUIPPED: at end of refresh, heal 3, add counter, discard at 3
    def refresh_cb(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            for pid in PID:
                if card.slot is g.players[pid].equipment:
                    yield from do(Heal(pid, 3, "Bellyfiller"))(g)  # pragma: no mutate
                    yield from do(AddCounter(card, "Bellyfiller"))(g)  # pragma: no mutate
                    if card.counters >= 3:
                        yield from do(Discard(pid, card, "Bellyfiller expired"))(g)  # pragma: no mutate
                    return
        return eff

    card.traits = [
        Trait.on_resolve(card, resolve_cb).instead(),
        Trait.while_equipped(card, TKind.AFTER,
            lambda a: isinstance(a, EndPhase) and a.phase == Phase.REFRESH,
            refresh_cb),
    ]
    return card
