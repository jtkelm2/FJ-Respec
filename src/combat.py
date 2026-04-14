from core.type import *
from core.engine import do

# --- Weapon usability ---

def can_use_weapon(ws: WeaponSlot, enemy: Card) -> bool:
    enemy_level = enemy.level
    assert enemy.is_type(CardType.ENEMY)
    assert enemy_level is not None
    return ws.sharpness() >= enemy_level

def _weapon_builder(g: GameState, player: PID, enemy: Card) -> PromptBuilder:
    enemy_level = enemy.level
    assert isinstance(enemy_level, int)

    pb = PromptBuilder(f"Fight Lv. {enemy_level} enemy:")  # pragma: no mutate
    pb.add(TextOption(f"Fists ({enemy_level} dmg)"))  # pragma: no mutate
    for ws in g.players[player].weapon_slots:
        if ws.can_fight(enemy_level):
            pb.add(WeaponSlotOption(ws))  # pragma: no mutate
    pb.context(CardOption(enemy))  # pragma: no mutate
    return pb


# --- Combat resolution ---

def resolve_combat(resolver: PID, enemy: Card) -> Effect:
    def effect(g: GameState) -> Negotiation:
        enemy_level = enemy.level
        assert enemy_level is not None

        pb = _weapon_builder(g, resolver, enemy)
        r = yield pb.build(resolver)
        ws: WeaponSlot | None
        match r[resolver]:
            case TextOption(_):
                ws = None
                sharpness = 0
            case WeaponSlotOption(weapon_slot):
                ws = weapon_slot
                sharpness = ws.sharpness()
            case _:
                raise ValueError(f"Unexpected response: {r[resolver]}")

        dmg = max(0, enemy_level - sharpness)
        yield from do(Damage(resolver, dmg, "combat"))(g)  # pragma: no mutate
        yield from do(Slay(resolver, enemy, ws, "ordinary combat"))(g)  # pragma: no mutate
    return effect
