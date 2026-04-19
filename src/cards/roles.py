from cards.effect_utils import _const
from typing import Callable
from core.type import (
    Card, CardType, Trait, TKind, PID, other, Phase, Alignment, Role,
    Action, Damage, Heal, Eat, Wield, Resolve, Discard, Slay, Refresh,
    Death as DeathAction, AddToKillstack, AssignRoleCard,
    EndPhase, EndActionPhase, SetHP, AddCounter,
    would_kill_enemy,
    Modifier, MKind, CanCallGuards, CanRun, Sharpness,
    Effect, GameState, Negotiation,
    PromptBuilder, TextOption, CardOption,
    WORLD_NAME,
)
from core.engine import do, query


def role_card(good: bool) -> Card:
    if good:
        return Card("human", "Human", "", None, (CardType.EQUIPMENT,))  # pragma: no mutate
    return Card("???", "???", "", None, (CardType.EQUIPMENT,))  # pragma: no mutate


# --- Foo(d) Fighter (bad_role_3) -----------------------------------------
# Whenever you would wield a weapon, instead eat it as food.
# Whenever you would eat food, instead wield it as a weapon.

def food_fighter() -> Card:
    card = Card(
        "food_fighter", "Foo(d) Fighter",  # pragma: no mutate
        "Whenever you would wield a weapon, instead eat it as food.\n"  # pragma: no mutate
        "Whenever you would eat food, instead wield it as a weapon.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,),
    )

    passthrough: bool = False

    def _wield_swap(pid: PID) -> Trait:
        def cb(a: Action) -> Effect:
            assert isinstance(a, Wield)
            def eff(g:GameState) -> Negotiation:
              nonlocal passthrough
              passthrough = True
              yield from do(Eat(a.player, a.card, "Foo(d) Fighter"))(g)
              passthrough = False
            return eff
        return Trait(f"{card.display_name} (Wield→Eat)", TKind.REPLACEMENT,  # pragma: no mutate
                     lambda a: isinstance(a, Wield) and a.player == pid and not passthrough,
                     cb)

    def _eat_swap(pid: PID) -> Trait:
        def cb(a: Action) -> Effect:
            assert isinstance(a, Eat)
            def eff(g:GameState) -> Negotiation:
                nonlocal passthrough
                passthrough = True
                yield from do(Wield(a.player, a.card, "Foo(d) Fighter"))(g)
                passthrough = False
            return eff
        return Trait(f"{card.display_name} (Eat→Wield)", TKind.REPLACEMENT,  # pragma: no mutate
                     lambda a: isinstance(a, Eat) and a.player == pid and not passthrough,
                     cb)

    def _setup(pid: PID) -> Effect:
        def eff(g: GameState) -> Negotiation:
            g.active_traits.append(_wield_swap(pid))
            g.active_traits.append(_eat_swap(pid))
            return; yield  # pragma: no cover
        return eff

    card.traits = [Trait.on_role_assign(card, _setup)]
    return card


# --- Corruption (bad_role_4) ---------------------------------------------
# Heal 6HP per turn at the end of your Refresh Phase.
# Whenever you would heal by any other means, instead take that much damage.

def corruption() -> Card:
    card = Card(
        "corruption", "Corruption",  # pragma: no mutate
        "Heal 6HP per turn at the end of your Refresh Phase.\n"  # pragma: no mutate
        "Whenever you would heal by any other means, instead take that much damage.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,),
    )
    def _refresh_heal(pid: PID) -> Trait:
        def cb(a: Action) -> Effect:
            def eff(g: GameState) -> Negotiation:
                yield from do(SetHP(pid, g.players[pid].hp + 6, "Corruption"))(g)
            return eff
        return Trait(f"{card.display_name} (Refresh Heal)", TKind.AFTER,  # pragma: no mutate
                     lambda a: isinstance(a, EndPhase) and a.phase == Phase.REFRESH,
                     cb)

    def _heal_flip(pid: PID) -> Trait:
        def cb(a: Action) -> Effect:
            assert isinstance(a, Heal)
            return do(Damage(a.target, a.amount, "Corruption"))
        return Trait(f"{card.display_name} (Heal→Damage)", TKind.REPLACEMENT,  # pragma: no mutate
                     lambda a: isinstance(a, Heal) and a.target == pid,
                     cb)

    def _setup(pid: PID) -> Effect:
        def eff(g: GameState) -> Negotiation:
            g.active_traits.append(_refresh_heal(pid))
            g.active_traits.append(_heal_flip(pid))
            return; yield  # pragma: no cover
        return eff

    card.traits = [Trait.on_role_assign(card, _setup)]
    return card


# --- The Poet (bad_role_6) -----------------------------------------------
# When you would fight a non-guard enemy, you may choose to refresh it instead.
# Your weapons discard on first use.

def the_poet() -> Card:
    card = Card(
        "the_poet", "The Poet",  # pragma: no mutate
        "When you would fight a non-guard enemy, you may choose to refresh it instead.\n"  # pragma: no mutate
        "Your weapons discard on first use.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,),
    )

    passthrough: bool = False

    def _persuasion(pid: PID) -> Trait:
        def cb(a: Action) -> Effect:
            def eff(g: GameState) -> Negotiation:
                assert isinstance(a, Resolve)
                response = yield PromptBuilder(f"Refresh enemy {card.display_name}?").add(TextOption("Yes")).add(TextOption("No")).build(pid)
                if response == TextOption("Yes"):
                    yield from do(Refresh(a.card, pid, "Refresh (Poet ability)"))(g)
                else:
                    nonlocal passthrough
                    passthrough = True
                    yield from do(a)(g)
                    passthrough = False
            return eff
        
        def _non_guard_enemy_resolve(a: Action) -> bool:
            return isinstance(a, Resolve) and a.card.is_type(CardType.ENEMY) and not a.card.name.startswith("guard_")
        
        return Trait(f"Permanent Poet ability", TKind.REPLACEMENT, _non_guard_enemy_resolve, cb)
            

    def _weapon_discard(pid: PID) -> Trait:
        def cb(a: Action) -> Effect:
            assert isinstance(a, Slay)
            def eff(g: GameState) -> Negotiation:
                if a.ws is not None and a.ws.weapon is not None:
                    yield from do(Discard(a.slayer, a.ws.weapon, "The Poet"))(g)  # pragma: no mutate
                    for c in list(a.ws.killstack.cards):
                        yield from do(Discard(a.slayer, c, "The Poet kill pile"))(g)  # pragma: no mutate
            return eff
        return Trait(f"{card.display_name} (Weapon Discard)", TKind.AFTER,  # pragma: no mutate
                     lambda a: isinstance(a, Slay) and a.slayer == pid and a.ws is not None,
                     cb)

    def _setup(pid: PID) -> Effect:
        def eff(g: GameState) -> Negotiation:
            g.active_traits.append(_persuasion(pid))
            g.active_traits.append(_weapon_discard(pid))
            return; yield  # pragma: no cover
        return eff

    card.traits = [Trait.on_role_assign(card, _setup)]
    return card


# --- The World role (bad_role_7) -----------------------------------------
# If The World dies on your action field, so do you.
# While equipped: If you would kill a non-guard enemy, you may instead
# place it in the other player's refresh pile.

def the_world_role() -> Card:
    card = Card(
        "the_world_role", "The World",  # pragma: no mutate
        "If The World dies on your action field, so do you.\n"  # pragma: no mutate
        "While equipped: If you would kill a non-guard enemy, you may instead "  # pragma: no mutate
        "place it in the other player's refresh pile.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,),
    )
    # While equipped: optional slay redirect (uses passthrough pattern)
    world_slay_passthrough = False
    def world_slay_applies(a: Action) -> bool:
        if world_slay_passthrough: return False
        return isinstance(a, Slay) and not a.enemy.name.startswith("guard_")

    def slay_redirect_cb(a: Action) -> Effect:
        assert isinstance(a, Slay)
        def eff(g: GameState) -> Negotiation:
            nonlocal world_slay_passthrough
            opp = other(a.slayer)
            pb = (PromptBuilder("The World: Refresh enemy to opponent instead of killing?")  # pragma: no mutate
                  .add(TextOption("Kill normally"))  # pragma: no mutate
                  .add(TextOption("Refresh to opponent")))  # pragma: no mutate
            response = yield pb.build(a.slayer)
            if response[a.slayer] == TextOption("Refresh to opponent"):
                yield from do(Refresh(a.enemy, opp, "The World role"))(g)  # pragma: no mutate
            else:
                world_slay_passthrough = True
                yield from do(a)(g)
                world_slay_passthrough = False
        return eff

    # Permanent: If The World dies on your action field, so do you
    def _world_death_trait(pid: PID) -> Trait:
        def _is_world_kill(a: Action) -> bool:
            match a:
                case AddToKillstack(enemy, _, _, _) if enemy.name == WORLD_NAME: return True
                case Discard(_, c, _) if c.name == WORLD_NAME:
                    return True
            return False

        def cb(a: Action) -> Effect:
            def eff(g: GameState) -> Negotiation:
                match a:
                    case AddToKillstack(enemy, _, _, _): killed_card = enemy
                    case Discard(_, c, _): killed_card = c
                    case _: return
                af_slots = g.players[pid].action_field.slots_in_fill_order()
                if any(killed_card.slot is s for s in af_slots):
                    yield from do(DeathAction(pid, "The World role"))(g)
            return eff
        return Trait(f"{card.display_name} (World Death)", TKind.BEFORE,  # pragma: no mutate
                     _is_world_kill, cb)

    def _setup(pid: PID) -> Effect:
        def eff(g: GameState) -> Negotiation:
            g.active_traits.append(_world_death_trait(pid))
            return; yield  # pragma: no cover
        return eff

    card.traits = [
        Trait.while_equipped(card, TKind.REPLACEMENT,
            world_slay_applies,
            slay_redirect_cb),
        Trait.on_role_assign(card, _setup),
    ]
    return card


# --- Leo (bad_role_9) ----------------------------------------------------
# Your HP cap starts at 9.
# Whenever you die, reduce your HP cap by 1 then revive to full HP.

def leo() -> Card:
    card = Card(
        "leo", "Leo",  # pragma: no mutate
        "Your HP cap starts at 9.\n"  # pragma: no mutate
        "Whenever you die, reduce your HP cap by 1 then revive to full HP.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,),
    )
    def _revival_trait(pid: PID) -> Trait:
        def cb(a: Action) -> Effect:
            assert isinstance(a, DeathAction)
            def eff(g: GameState) -> Negotiation:
                p = g.players[pid]
                p.hp_cap -= 1
                if p.hp_cap <= 0:
                    p.is_dead = True
                    return
                yield from do(SetHP(pid, p.hp_cap, "Leo"))(g)  # pragma: no mutate
            return eff
        return Trait(f"{card.display_name} (Revival)", TKind.REPLACEMENT,  # pragma: no mutate
                     lambda a: isinstance(a, DeathAction) and a.target == pid,
                     cb)


    def _setup(pid: PID) -> Effect:
        def eff(g: GameState) -> Negotiation:
            g.players[pid].hp_cap = 9
            g.active_traits.append(_revival_trait(pid))
            yield from do(SetHP(pid, 9, "Leo setup"))(g)  # pragma: no mutate
        return eff

    card.traits = [Trait.on_role_assign(card, _setup)]
    return card


# --- Detective (good_role_8) ---------------------------------------------
# You cannot call the guards.
# On discard: You may look through your entire deck and refresh pile.

def detective() -> Card:
    card = Card(
        "detective", "Detective",  # pragma: no mutate
        "You cannot call the guards.\n"  # pragma: no mutate
        "On discard: You may look through your entire deck and refresh pile.",  # pragma: no mutate
        None, (CardType.EQUIPMENT,),
    )
    def _setup(player: PID) -> Effect:
        """Install a CanCallGuards INTERCEPT modifier on the game state."""
        def eff(g: GameState) -> Negotiation:
            g.active_modifiers.append(Modifier(
                f"{card.display_name} (No Guards)",  # pragma: no mutate
                MKind.INTERCEPT,
                lambda q: isinstance(q, CanCallGuards) and q.player == player,
                _const(0)))
            return; yield  # pragma: no cover
        return eff

    def discard_cb(a: Action) -> Effect:
        assert isinstance(a, Discard)
        def eff(g: GameState) -> Negotiation:
            pid = a.discarder
            p = g.players[pid]
            deck_cards = list(p.deck.cards)
            refresh_cards = list(p.refresh.cards)
            pb = PromptBuilder("Detective: Your deck and refresh pile")  # pragma: no mutate
            for c in deck_cards + refresh_cards:
                pb.context(CardOption(c))
            pb.add(TextOption("OK"))  # pragma: no mutate
            yield pb.build(pid)
        return eff

    card.traits = [
        Trait.on_discard(card, discard_cb),
        Trait.on_role_assign(card, _setup),
    ]
    return card


############ Role registry ##############################

# Each entry: (factory, Role).
# factory() -> Card produces the role card with traits/modifiers.
# Role carries the name and alignment for PlayerState.

GOOD_ROLES: list[tuple[Callable[[], Card], Role]] = [
    (lambda: role_card(good=True), Role("Human", Alignment.GOOD)),
    (detective,    Role("Detective", Alignment.GOOD)),
]

EVIL_ROLES: list[tuple[Callable[[], Card], Role]] = [
    (lambda: role_card(good=False), Role("???", Alignment.EVIL)),
    (food_fighter, Role("Foo(d) Fighter", Alignment.EVIL)),
    (corruption,   Role("Corruption", Alignment.EVIL)),
    (the_poet,     Role("The Poet", Alignment.EVIL)),
    (the_world_role, Role("The World", Alignment.EVIL)),
    (leo,          Role("Leo", Alignment.EVIL)),
]
