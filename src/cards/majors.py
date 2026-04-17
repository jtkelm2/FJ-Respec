from core.type import (
    Card, CardType, Trait, TKind, PID, other, Phase, Alignment,
    Action, Resolve, Damage, Heal, Refresh, SetHP, Discard, Death as DeathAction,
    EnsureDeck, Slot2Slot, EndPhase, TransferHP, Equip, Wield, Slay,
    AddCounter, EndActionPhase,
    Modifier, MKind, Sharpness, WORLD_NAME,
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
    def _mod(_q, v):
        def eff(_g):
            return v + 1; yield  # pragma: no cover
        return eff
    card.modifiers = [Modifier.while_equipped(card,
        lambda q: isinstance(q, Sharpness) and _card_belongs_to(card, q.player),
        _mod)]
    return card


# --- Strength (major_8) ---------------------------------------------------
# While equipped: You may discard this to wield it as a weapon.
# As a weapon: Every time this kills an enemy: Discard the enemy, then the
# other player rolls a d20 and declares the result. If the result is 10 or
# less, place a counter on this. For Good only, this has -1 level per counter.

def strength() -> Card:
    card = Card(
        "major_8", "Strength",  # pragma: no mutate
        "While equipped: You may discard this to wield it as a weapon.\n"  # pragma: no mutate
        "As a weapon: Every time this kills an enemy: Discard the enemy, then the "  # pragma: no mutate
        "other player rolls a d20 and declares the result. If the result is 10 or "  # pragma: no mutate
        "less, place a counter on this. For Good only, this has -1 level per counter.",  # pragma: no mutate
        8, (CardType.EQUIPMENT, CardType.WEAPON), False, False,
    )
    # While equipped: discard → wield instead
    def equip_discard_cb(a: Action) -> Effect:
        assert isinstance(a, Discard)
        def eff(g: GameState) -> Negotiation:
            yield from do(Wield(a.discarder, card, "Strength"))(g)  # pragma: no mutate
        return eff

    # As a weapon: on kill, discard enemy + opponent d20 + counter
    def kill_cb(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            yield from do(Discard(a.slayer, a.enemy, "Strength"))(g)  # pragma: no mutate
            opp = other(a.slayer)
            roll = g.rng.randint(1, 20)
            p_opp = g.players[opp]
            pb = PromptBuilder("Strength: Roll d20 and declare result")  # pragma: no mutate
            if p_opp.alignment == Alignment.GOOD:
                pb.add(TextOption(str(roll)))  # pragma: no mutate
            else:
                for i in range(1, 21):
                    pb.add(TextOption(str(i)))  # pragma: no mutate
            response = yield pb.build(opp)
            response_opp = response[opp]
            assert isinstance(response_opp, TextOption)
            declared = int(response_opp.text)
            if declared <= 10:
                yield from do(AddCounter(card, "Strength"))(g)  # pragma: no mutate
        return eff

    card.traits = [
        Trait.while_equipped(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Discard) and a.card is card,
            equip_discard_cb),
        Trait.slays_enemy(card, TKind.AFTER, kill_cb),
    ]

    # Sharpness modifier: -1 per counter, for Good only
    def _sharpness_mod(q, v):
        def eff(g):
            if g.players[q.player].alignment == Alignment.GOOD:
                return v - card.counters
            return v
            yield  # pragma: no cover
        return eff
    
    card.modifiers = [Modifier.as_a_weapon(card,
        lambda q: isinstance(q, Sharpness) and q.ws.weapon is card,
        _sharpness_mod)]
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


# --- The Magician (major_1) ----------------------------------------------
# On resolve: Look at the top 3 cards of the deck, and resolve one of them.
# Place the other 2 cards in the refresh pile.

def the_magician() -> Card:
    card = Card(
        "major_1", "The Magician",  # pragma: no mutate
        "On resolve: Look at the top 3 cards of the deck, and resolve one of them. "  # pragma: no mutate
        "Place the other 2 cards in the refresh pile.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            p = g.players[resolver]
            drawn: list[Card] = []
            for _ in range(3):
                yield from do(EnsureDeck(resolver, "The Magician"))(g)  # pragma: no mutate
                if p.is_dead: return
                yield from do(Slot2Slot(p.deck, p.sidebar, "The Magician"))(g)  # pragma: no mutate
                drawn.append(p.sidebar.cards[0])
            pb = PromptBuilder("The Magician: Resolve which card?")  # pragma: no mutate
            pb.add_cards(drawn)
            response = yield pb.build(resolver)
            response_resolver = response[resolver]
            assert isinstance(response_resolver, CardOption)
            chosen = response_resolver.card
            for c in drawn:
                if c is not chosen:
                    yield from do(Refresh(c, resolver, "The Magician"))(g)  # pragma: no mutate
            yield from do(Resolve(resolver, chosen, "The Magician"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_resolve(card, callback)]
    return card


# --- The Chariot (major_7) -----------------------------------------------
# On resolve: Take 7 damage.
# While equipped: You may discard this to prevent any single instance of damage.

def the_chariot() -> Card:
    card = Card(
        "major_7", "The Chariot",  # pragma: no mutate
        "On resolve: Take 7 damage.\n"  # pragma: no mutate
        "While equipped: You may discard this to prevent any single instance of damage.",  # pragma: no mutate
        None, (CardType.EVENT, CardType.EQUIPMENT), False, False,
    )
    def resolve_cb(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            yield from do(Damage(resolver, 7, "The Chariot"))(g)
            if g.players[resolver].is_dead: return
            yield from do(Equip(resolver, card, "The Chariot"))(g)  # pragma: no mutate
        return eff

    def damage_cb(a: Action) -> Effect:
        assert isinstance(a, Damage)
        def eff(g: GameState) -> Negotiation:
            for pid in PID:
                if card.slot is g.players[pid].equipment:
                    pb = (PromptBuilder(f"The Chariot: Discard to prevent {a.amount} damage?")  # pragma: no mutate
                          .add(TextOption("Prevent"))  # pragma: no mutate
                          .add(TextOption("Take damage")))  # pragma: no mutate
                    response = yield pb.build(pid)
                    if response[pid] == TextOption("Prevent"):
                        yield from do(Discard(pid, card, "The Chariot"))(g)  # pragma: no mutate
                    else:
                        yield from do(a)(g)
        return eff

    card.traits = [
        Trait.on_resolve(card, resolve_cb).instead(),
        Trait.while_equipped(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Damage) and a.amount > 0,
            damage_cb),
    ]
    return card


# --- Death (major_13) ----------------------------------------------------
# On resolve: Discard all adjacent action cards. Your Action Phase ends now.

def _adjacent_slots(slot, g):
    top_row = [
        g.players[PID.BLUE].action_field.top_distant,
        g.players[PID.BLUE].action_field.top_hidden,
        g.players[PID.RED].action_field.top_hidden,
        g.players[PID.RED].action_field.top_distant,
    ]
    bot_row = [
        g.players[PID.BLUE].action_field.bottom_distant,
        g.players[PID.BLUE].action_field.bottom_hidden,
        g.players[PID.RED].action_field.bottom_hidden,
        g.players[PID.RED].action_field.bottom_distant,
    ]
    rows = [top_row, bot_row]
    pos = None
    for r, row in enumerate(rows):
        for c_idx, s in enumerate(row):
            if s is slot:
                pos = (r, c_idx)
                break
    if pos is None:
        return []
    r, c_idx = pos
    adj = []
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nr, nc = r + dr, c_idx + dc
        if 0 <= nr < len(rows) and 0 <= nc < len(rows[nr]):
            adj.append(rows[nr][nc])
    return adj

def death_card() -> Card:
    card = Card(
        "major_13", "Death",  # pragma: no mutate
        "On resolve: Discard all adjacent action cards. Your Action Phase ends now.",  # pragma: no mutate
        None, (CardType.EVENT,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            slot = card.slot
            if slot is not None:
                for adj_slot in _adjacent_slots(slot, g):
                    for c in list(adj_slot.cards):
                        yield from do(Discard(resolver, c, "Death"))(g)  # pragma: no mutate
            yield from do(EndActionPhase(resolver, "Death"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_resolve(card, callback)]
    return card


# --- The Tower (major_16) ------------------------------------------------
# On resolve: You die!

def the_tower() -> Card:
    card = Card(
        "major_16", "The Tower",  # pragma: no mutate
        "On resolve: You die!",  # pragma: no mutate
        None, (CardType.EVENT,), True, False,  # Elusive
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Resolve)
        resolver = a.resolver
        def eff(g: GameState) -> Negotiation:
            yield from do(DeathAction(resolver, "The Tower"))(g)
        return eff
    card.traits = [Trait.on_resolve(card, callback)]
    return card


# --- Judgement (major_20) ------------------------------------------------
# While equipped: You may discard this to wield it as a weapon.
# As a weapon: Discards after one use.

def judgement() -> Card:
    card = Card(
        "major_20", "Judgement",  # pragma: no mutate
        "While equipped: You may discard this to wield it as a weapon.\n"  # pragma: no mutate
        "As a weapon: Discards after one use.",  # pragma: no mutate
        20, (CardType.EQUIPMENT, CardType.WEAPON), False, False,
    )
    # While equipped: discard → wield instead
    def equip_discard_cb(a: Action) -> Effect:
        assert isinstance(a, Discard)
        def eff(g: GameState) -> Negotiation:
            yield from do(Wield(a.discarder, card, "Judgement"))(g)  # pragma: no mutate
        return eff

    # As a weapon: discard after any kill
    def kill_cb(a: Action) -> Effect:
        assert isinstance(a, Slay)
        assert a.ws is not None
        ws = a.ws
        def eff(g: GameState) -> Negotiation:
            yield from do(Discard(a.slayer, card, "Judgement one-use"))(g)  # pragma: no mutate
            for c in list(ws.killstack.cards):
                yield from do(Discard(a.slayer, c, "Judgement kill pile"))(g)  # pragma: no mutate
        return eff

    card.traits = [
        Trait.while_equipped(card, TKind.REPLACEMENT,
            lambda a: isinstance(a, Discard) and a.card is card,
            equip_discard_cb),
        Trait.as_a_weapon(card, TKind.AFTER,
            lambda a: isinstance(a, Slay) and a.ws is not None,
            kill_cb),
    ]
    return card


# --- The World (major_21) ------------------------------------------------
# Boss enemy, level 21. Elusive.

def the_world() -> Card:
    return Card(
        WORLD_NAME, "The World",  # pragma: no mutate
        "After death: If both copies of this card are dead, then two Good players may claim victory!",  # pragma: no mutate
        21, (CardType.ENEMY,), True, False,  # Elusive
    )
