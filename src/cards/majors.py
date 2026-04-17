from core.type import (
    Card, CardType, Trait, TKind, PID, other, Phase, Alignment,
    Action, Resolve, Damage, Heal, Refresh, SetHP, Discard,
    EnsureDeck, Slot2Slot, EndPhase, TransferHP,
    Modifier, Sharpness,
    Effect, GameState, Negotiation,
    PromptBuilder, TextOption, CardOption,
)
from core.engine import do


# --- The Fool (major_0) --------------------------------------------------
# On resolve: Look at the top card of the deck and resolve it.

def the_fool() -> Card:
    card = Card(
        "major_0", "The Fool",  # pragma: no mutate
        "On resolve: Look at the top card of the deck and resolve it.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def effect(g: GameState) -> Negotiation:
            p = g.players[resolver]
            yield from do(EnsureDeck(resolver, "the Fool"))(g)  # pragma: no mutate
            if p.is_dead: return
            yield from do(Slot2Slot(p.deck, p.sidebar, "the Fool"))(g)  # pragma: no mutate
            top = p.sidebar.cards[0]
            yield from do(Resolve(resolver, top, "the Fool"))(g)  # pragma: no mutate
        return effect
    card.traits = [Trait.on_resolve(card, callback)]  # pragma: no mutate
    return card


# --- The Empress (major_3) -----------------------------------------------
# While equipped: Heal 1 at the end of the Refresh Phase.

def the_empress() -> Card:
    card = Card(
        "major_3", "The Empress",  # pragma: no mutate
        "While equipped: Heal 1 at the end of the Refresh Phase.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            for pid in PID:
                if card.slot is g.players[pid].equipment:
                    yield from do(Heal(pid, 1, "The Empress"))(g)  # pragma: no mutate
                    return
        return eff
    card.traits = [Trait.while_equipped(card, TKind.AFTER,
        lambda a: isinstance(a, EndPhase) and a.phase == Phase.REFRESH,
        callback)]
    return card


# --- The Emperor (major_4) ------------------------------------------------
# While equipped: Add +1 to your weapons level.

def _card_belongs_to(card: Card, pid: PID) -> bool:
    return card.slot is not None and card.slot.name.startswith(pid.name.lower())

def the_emperor() -> Card:
    card = Card(
        "major_4", "The Emperor",  # pragma: no mutate
        "While equipped: Add +1 to your weapons level.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,), False, False,
    )
    card.modifiers = [Modifier.while_equipped(card,
        lambda q: isinstance(q, Sharpness) and _card_belongs_to(card, q.player),
        lambda q, v: v + 1)]
    return card


# --- The Lovers (major_6) ------------------------------------------------
# On resolve: Give the other player any amount of HP (may be zero).
# Then take 1 damage.

def the_lovers() -> Card:
    card = Card(
        "major_6", "The Lovers",  # pragma: no mutate
        "On resolve: Give the other player any amount of HP (may be zero). Then take 1 damage.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            p = g.players[resolver]
            pb = PromptBuilder("The Lovers: Give how much HP?")  # pragma: no mutate
            for i in range(p.hp + 1):
                pb.add(TextOption(str(i)))  # pragma: no mutate
            response = yield pb.build(resolver)
            amount_opt = response[resolver]
            assert isinstance(amount_opt, TextOption)
            amount = int(amount_opt.text)
            if amount > 0:
                yield from do(TransferHP(resolver, other(resolver), amount, "The Lovers"))(g)  # pragma: no mutate
            yield from do(Damage(resolver, 1, "The Lovers"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_resolve(card, callback)]
    return card


# --- The Hermit (major_9) ------------------------------------------------
# You may choose to: Give the other player 1HP.
# Then, if you are Good, discard a piece of equipment and heal d10 HP.
# If you are Evil, take d20 damage.

def the_hermit() -> Card:
    card = Card(
        "major_9", "The Hermit",  # pragma: no mutate
        "You may choose to: Give the other player 1HP.\n"  # pragma: no mutate
        "Then, if you are Good, discard a piece of equipment and heal d10 HP. "  # pragma: no mutate
        "If you are Evil, take d20 damage.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            p = g.players[resolver]
            pb = (PromptBuilder("The Hermit: Give the other player 1 HP?")  # pragma: no mutate
                  .add(TextOption("Yes"))  # pragma: no mutate
                  .add(TextOption("No")))  # pragma: no mutate
            response = yield pb.build(resolver)
            if response[resolver] == TextOption("Yes"):
                yield from do(TransferHP(resolver, other(resolver), 1, "The Hermit"))(g)  # pragma: no mutate

            if p.alignment == Alignment.GOOD:
                equips = list(p.equipment.cards)
                if equips:
                    epb = PromptBuilder("The Hermit: Discard which equipment?")  # pragma: no mutate
                    epb.add_cards(equips)
                    response = yield epb.build(resolver)
                    response_card = response[resolver]
                    assert isinstance(response_card, CardOption)
                    yield from do(Discard(resolver, response_card.card, "The Hermit"))(g)  # pragma: no mutate
                    heal = g.rng.randint(1, 10)
                    yield from do(Heal(resolver, heal, "The Hermit"))(g)  # pragma: no mutate
            else:
                dmg = g.rng.randint(1, 20)
                yield from do(Damage(resolver, dmg, "The Hermit"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_resolve(card, callback)]
    return card


# --- The Wheel of Fortune (major_10) -------------------------------------
# On resolve: Roll a d20. Set your HP equal to the result.

def the_wheel_of_fortune() -> Card:
    card = Card(
        "major_10", "The Wheel of Fortune",  # pragma: no mutate
        "On resolve: Roll a d20. Set your HP equal to the result.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            roll = g.rng.randint(1, 20)
            yield from do(SetHP(resolver, roll, "Wheel of Fortune"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_resolve(card, callback)]
    return card


# --- Justice (major_11) --------------------------------------------------
# On resolve: Deal 5 damage to the other player. Put this into the
# refresh pile.

def justice() -> Card:
    card = Card(
        "major_11", "Justice",  # pragma: no mutate
        "On resolve: Deal 5 damage to the other player. Put this into the refresh pile.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def effect(g: GameState) -> Negotiation:
            yield from do(Damage(other(resolver), 5, "Justice"))(g)
            yield from do(Refresh(card, resolver, "Justice"))(g)  # pragma: no mutate
        return effect
    card.traits = [Trait.on_resolve(card, callback).instead()]
    return card


# --- The Hanged Man (major_12) -------------------------------------------
# On resolve: Deal 5 damage to the other player, and heal yourself for 7.
# Put this into the refresh pile.

def the_hanged_man() -> Card:
    card = Card(
        "major_12", "The Hanged Man",  # pragma: no mutate
        "On resolve: Deal 5 damage to the other player, and heal yourself for 7. "  # pragma: no mutate
        "Put this into the refresh pile.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            yield from do(Damage(other(resolver), 5, "The Hanged Man"))(g)
            yield from do(Heal(resolver, 7, "The Hanged Man"))(g)  # pragma: no mutate
            yield from do(Refresh(card, resolver, "The Hanged Man"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_resolve(card, callback).instead()]
    return card
