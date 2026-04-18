from cards.effect_utils import _const, _kill_slayer
from core.type import (
    Card, CardType, Trait, TKind, Modifier, MKind,
    EnemyLevel, CanRun,
    Action, Slay, AddToKillstack, Discard, Damage, Wield, Refresh, Slot2Slot, SlotKind,
    EnsureDeck,
    PID, other,
    Effect, GameState, Negotiation,
)
from core.engine import do


def enemy(level: int) -> Card:
    return Card(f"enemy_{level}", f"Enemy ({level})", "", level, (CardType.ENEMY,), False, False)  # pragma: no mutate

def guard(level: int) -> Card:
    card = Card(
        f"guard_{level}", f"Guard ({level})",  # pragma: no mutate
        "You cannot run while this is on your field.\n"  # pragma: no mutate
        "On kill: Refresh this.\n"  # pragma: no mutate
        "On placement: If this has nothing beneath it, draw another card beneath this.",  # pragma: no mutate
        level, (CardType.ENEMY,), False, False,
    )
    # On kill: refresh instead of killstack/discard
    def kill_cb(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            yield from do(Refresh(card, _kill_slayer(a), "guard"))(g)  # pragma: no mutate
        return eff

    # On placement: draw underneath if nothing beneath
    def placement_cb(a: Action) -> Effect:
        assert isinstance(a, Slot2Slot)
        def eff(g: GameState) -> Negotiation:
            dest = a.dest
            if len(dest.cards) == 1:  # only this guard, nothing beneath
                for pid in PID:
                    p = g.players[pid]
                    if dest in p.action_field.slots_in_fill_order():
                        yield from do(EnsureDeck(pid, "guard"))(g)  # pragma: no mutate
                        if p.is_dead: return
                        card_idx = dest.cards.index(card)
                        yield from do(Slot2Slot(p.deck, dest, "guard", dest_index=card_idx + 1))(g)  # pragma: no mutate
                        return
        return eff

    card.traits = [
        Trait.on_kill(card, kill_cb).instead(),
        Trait.on_placement(card, placement_cb),
    ]

    # Cannot run while this is on your field
    card.modifiers = [Modifier(
        f"{card.display_name} (No Run)",  # pragma: no mutate
        MKind.INTERCEPT,
        lambda q: (isinstance(q, CanRun)
                   and card.slot is not None
                   and card.slot.kind == SlotKind.ACTION_FIELD
                   and card.slot.name.startswith(q.player.name.lower())),
        _const(0))]
    return card


# enemy_1 (Gobshite) — If attacking with your fists: This is a level 22 enemy.

def enemy_1() -> Card:
    card = Card(
        "enemy_1", "Gobshite (1)",  # pragma: no mutate
        "If attacking with your fists: This is a level 22 enemy.",  # pragma: no mutate
        1, (CardType.ENEMY,), False, False,
    )
    card.modifiers = [Modifier(
        f"{card.display_name} (Fists)",  # pragma: no mutate
        MKind.INTERCEPT,
        lambda q: isinstance(q, EnemyLevel) and q.enemy is card and q.ws is None,
        _const(22))]
    return card


# enemy_3 — If you kill this with a weapon: Discard this and your kill pile.

def enemy_3() -> Card:
    card = Card(
        "enemy_3", "Enemy (3)",  # pragma: no mutate
        "If you kill this with a weapon: Discard this and your kill pile.",  # pragma: no mutate
        3, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            if not isinstance(a, AddToKillstack): return  # weapon kills only
            for c in list(a.killstack.cards):
                yield from do(Discard(_kill_slayer(a), c, "enemy_3"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_kill(card, callback)]
    return card


# enemy_4 (Skeleton) — On placement: Draw another card underneath this.

def enemy_4() -> Card:
    card = Card(
        "enemy_4", "Skeleton (4)",  # pragma: no mutate
        "On placement: Draw another card underneath this.",  # pragma: no mutate
        4, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Slot2Slot)
        def eff(g: GameState) -> Negotiation:
            dest = a.dest
            for pid in PID:
                p = g.players[pid]
                if dest in p.action_field.slots_in_fill_order():
                    from core.type import EnsureDeck
                    yield from do(EnsureDeck(pid, "Skeleton"))(g)  # pragma: no mutate
                    if p.is_dead: return
                    card_idx = dest.cards.index(card)
                    yield from do(Slot2Slot(p.deck, dest, "Skeleton", dest_index=card_idx + 1))(g)  # pragma: no mutate
                    return
        return eff
    card.traits = [Trait.on_placement(card, callback)]
    return card


# enemy_7 — If you kill this with a weapon: Discard your weapon.

def enemy_7() -> Card:
    card = Card(
        "enemy_7", "Enemy (7)",  # pragma: no mutate
        "If you kill this with a weapon: Discard your weapon.",  # pragma: no mutate
        7, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            if not isinstance(a, AddToKillstack): return  # weapon kills only
            slayer = _kill_slayer(a)
            # Find the WeaponSlot that owns this killstack
            ws = next((ws for ws in g.players[slayer].weapon_slots
                       if ws.killstack is a.killstack), None)
            if ws is None: return
            if ws.weapon is not None:
                yield from do(Discard(slayer, ws.weapon, "enemy_7"))(g)  # pragma: no mutate
            for c in list(ws.killstack.cards):
                yield from do(Discard(slayer, c, "enemy_7 kill pile"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_kill(card, callback)]
    return card


# enemy_8 (Lonely Ogre) — On kill: Wield this as a weapon.

def enemy_8() -> Card:
    card = Card(
        "enemy_8", "Lonely Ogre (8)",  # pragma: no mutate
        "On kill: Wield this as a weapon.",  # pragma: no mutate
        8, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            yield from do(Wield(_kill_slayer(a), card, "Lonely Ogre"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_kill(card, callback).instead()]
    return card


# enemy_14 (BA Barockus) — On kill: Take 3 damage.

def enemy_14() -> Card:
    card = Card(
        "enemy_14", "BA Barockus (14)",  # pragma: no mutate
        "On kill: Take 3 damage.",  # pragma: no mutate
        14, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        def eff(g: GameState) -> Negotiation:
            yield from do(Damage(_kill_slayer(a), 3, "BA Barockus"))(g)
        return eff
    card.traits = [Trait.on_kill(card, callback)]
    return card
