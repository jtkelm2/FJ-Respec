from core.type import (
    Card, CardType, Trait, Modifier, MKind, EnemyLevel,
    Action, Slay, Discard, Damage,
    Effect, GameState, Negotiation,
)
from core.engine import do


def enemy(level: int) -> Card:
    return Card(f"enemy_{level}", f"Enemy ({level})", "", level, (CardType.ENEMY,), False, False)  # pragma: no mutate

def guard(level: int) -> Card:
    return Card(f"guard_{level}", f"Guard ({level})", "", level, (CardType.ENEMY,), False, False)  # pragma: no mutate


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
        lambda q, v: 22)]
    return card


# enemy_3 — If you kill this with a weapon: Discard this and your kill pile.

def enemy_3() -> Card:
    card = Card(
        "enemy_3", "Enemy (3)",  # pragma: no mutate
        "If you kill this with a weapon: Discard this and your kill pile.",  # pragma: no mutate
        3, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            if a.ws is None: return
            for c in list(a.ws.killstack.cards):
                yield from do(Discard(a.slayer, c, "enemy_3"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_kill(card, callback)]
    return card


# enemy_7 — If you kill this with a weapon: Discard your weapon.

def enemy_7() -> Card:
    card = Card(
        "enemy_7", "Enemy (7)",  # pragma: no mutate
        "If you kill this with a weapon: Discard your weapon.",  # pragma: no mutate
        7, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            if a.ws is None: return
            if a.ws.weapon is not None:
                yield from do(Discard(a.slayer, a.ws.weapon, "enemy_7"))(g)  # pragma: no mutate
            for c in list(a.ws.killstack.cards):
                yield from do(Discard(a.slayer, c, "enemy_7 kill pile"))(g)  # pragma: no mutate
        return eff
    card.traits = [Trait.on_kill(card, callback)]
    return card


# enemy_14 (BA Barockus) — On kill: Take 3 damage.

def enemy_14() -> Card:
    card = Card(
        "enemy_14", "BA Barockus (14)",  # pragma: no mutate
        "On kill: Take 3 damage.",  # pragma: no mutate
        14, (CardType.ENEMY,), False, False,
    )
    def callback(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            yield from do(Damage(a.slayer, 3, "BA Barockus"))(g)
        return eff
    card.traits = [Trait.on_kill(card, callback)]
    return card
