from core.type import *
from core.engine import do

# --- Weapon usability ---

def can_use_weapon(ws: WeaponSlot, enemy: Card) -> bool:
    enemy_level = enemy.level
    assert enemy.is_type(CardType.ENEMY)
    assert enemy_level is not None
    return ws.sharpness() >= enemy_level

def choose_weapon_prompt(g: GameState, player: PID, enemy: Card) -> Prompt:
    enemy_level = enemy.level
    assert isinstance(enemy_level, int)
    
    opts: list[str] = [f"Fists ({enemy_level} dmg)"]
    for ws in g.players[player].weapon_slots:
        if can_use_weapon(ws, enemy):
            assert ws.weapon is not None
            weapon_level = ws.weapon.level
            assert weapon_level is not None
            opts.append(f"Weapon Lv. {weapon_level} ({max(0, enemy_level - weapon_level)} dmg)")
    return Ask(player, f"Fight Lv. {enemy_level} enemy:", opts)


# --- Combat resolution ---

def resolve_combat(resolver: PID, enemy: Card) -> Effect:
    def effect(g: GameState) -> Negotiation:
        enemy_level = enemy.level
        assert enemy_level is not None

        r = yield choose_weapon_prompt(g, resolver, enemy)
        choice = r[resolver]

        ws:WeaponSlot | None
        sharpness:int
        if choice == 0:
            ws = None
            sharpness = 0
        else:
            ws = g.players[resolver].weapon_slots[choice-1]
            sharpness = ws.sharpness()

        dmg = max(0, enemy_level - sharpness)
        yield from do(Damage(resolver, dmg, "combat"))(g)
        yield from do(Slay(resolver, enemy, ws, "ordinary combat"))(g)
    return effect