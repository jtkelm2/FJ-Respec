from core.type import *
from core.interpret import *


def run(g:GameState, effect: Effect, i:Interpreter):
  e = effect(g)
  try:
    prompt = next(e)
    while True:
      response = i.interpret(prompt)
      prompt = e.send(response)
  except StopIteration:
    return

def do(action: Action) -> Effect:
    def effect(g: GameState) -> Negotiation:
        # Instead-of: find an applicable replacement and delegate to it.
        candidates = [ tr for tr in _get_triggers(g) if tr.kind == TKind.REPLACEMENT ]  # pragma: no mutate
        if candidates:  # pragma: no mutate
          if len(candidates) == 1:  # pragma: no mutate
            chosen = candidates[0]  # pragma: no mutate
          else:
            pid = _player_to_choose_replacement(g, action)  # pragma: no mutate
            response = yield Ask(pid, f"Choose replacement for {action}:", [tr.name for tr in candidates])  # pragma: no mutate
            chosen = candidates[response[pid]]  # pragma: no mutate
          yield from chosen.callback(action)(g)  # pragma: no mutate
          return  # pragma: no mutate

        # Before triggers
        yield from _fire_triggers(g, action, TKind.BEFORE)  # pragma: no mutate

        # Execute
        yield from _apply_action(action)(g)

        # After triggers
        yield from _fire_triggers(g, action, TKind.AFTER)  # pragma: no mutate
    return effect

def simultaneously(effects: dict[PID, Effect]) -> Effect:
    """Combinator for asynchronously combining Effects, via AskEither.

    Each effect must only yield single-player Ask prompts for its own PID.
    Pending prompts from both players are merged into one AskEither;
    whichever player the interpreter answers for has their generator advanced.
    """
    def effect(g: GameState) -> Negotiation:
        gens = {pid: eff(g) for pid, eff in effects.items()}
        pending: dict[PID, PromptHalf] = {}

        def _extract(prompt:Prompt, pid:PID):
            assert prompt.kind == PKind.EITHER and len(prompt.for_player) == 1
            return prompt.for_player[pid]

        for pid in PID:
            try: pending[pid] = _extract(next(gens[pid]), pid)
            except StopIteration: pass

        while pending:
            response = yield AskEither(pending)
            answered_pid = next(iter(response))
            del pending[answered_pid]
            try: pending[answered_pid] = _extract(gens[answered_pid].send(response), answered_pid)
            except StopIteration: pass

    return effect


################## Helpers #########

def _apply_action(action: Action) -> Effect:
    def effect(g:GameState) -> Negotiation:
        match action:
            case Death(target):
                p = g.players[target]
                p.is_dead = True
            case Refresh(card, player, source):
                yield from do(SlotCard(card, g.players[player].refresh, "refresh"))(g)  # pragma: no mutate
            case Discard(discarder, card, source):
                yield from do(SlotCard(card, g.players[discarder].discard, "discard"))(g)  # pragma: no mutate
            case Slay(slayer, enemy, ws, source):
                if ws is None:
                   yield from do(Discard(slayer, enemy, "combat (fists)"))(g)  # pragma: no mutate
                   return
                yield from do(SlotCard(enemy, ws.killstack, "slay"))(g)  # pragma: no mutate
            case SetHP(target, value, source):
                p = g.players[target]
                new_hp = value
                if p.hp_floor is not None:
                    new_hp = max(new_hp, p.hp_floor)
                if p.hp_ceiling is not None:
                    new_hp = min(new_hp, p.hp_ceiling)
                p.hp = new_hp
                if p.hp <= 0:
                    yield from do(Death(target))(g)
            case SlotCard(card, slot, source):
                slot.slot(card)
            case Slot2Slot(orig, dest, source):
                if orig.is_empty(): return
                dest.slot(orig.draw())
            case Slot2SlotAll(orig, dest, source):
                dest.slot(*orig.cards)
            case Heal(target, amount, source):
                yield from do(SetHP(target, g.players[target].hp + amount, source))(g)  # pragma: no mutate
            case Damage(target, amount, source):
                yield from do(SetHP(target, g.players[target].hp - amount, source))(g)  # pragma: no mutate
            case Shuffle(slot, source):
                g.shuffle(slot)
            case ShuffleRefreshIntoDeck(player, source):
                p = g.players[player]
                yield from do(Slot2SlotAll(p.refresh, p.deck, "shuffle refresh"))(g)  # pragma: no mutate
                yield from do(Shuffle(p.deck, "shuffle refresh"))(g)  # pragma: no mutate
            case EnsureDeck(player, source):
                p = g.players[player]
                if p.deck.is_empty():
                    yield from do(ShuffleRefreshIntoDeck(player, "exhaustion recovery"))(g)  # pragma: no mutate
                if p.deck.is_empty():
                    for pid in PID:
                        yield from do(Death(pid, source="exhaustion"))(g)  # pragma: no mutate
            case Draw(player):
                yield from do(EnsureDeck(other(player),"draw to hand"))(g)  # pragma: no mutate
                yield from do(Slot2Slot(g.players[other(player)].deck, g.players[player].hand, "draw"))(g)  # pragma: no mutate
            case Equip(player, card, source):
                p = g.players[player]
                while len(p.equipment.cards) >= p.max_equipment:
                    response = yield Ask(player, "Equipment full. Discard which?", [c.display_name for c in p.equipment.cards])  # pragma: no mutate
                    to_discard = p.equipment.cards[response[player]]
                    yield from do(Discard(player, to_discard, "equip overflow"))(g)  # pragma: no mutate
                yield from do(SlotCard(card, p.equipment, "equip"))(g)  # pragma: no mutate
            case Wield(player, card, source):
                p = g.players[player]
                if len(p.weapon_slots) == 1:
                    ws = p.weapon_slots[0]
                else:
                    opts = []  # pragma: no mutate
                    for i, ws in enumerate(p.weapon_slots):
                        if ws.weapon is not None:  # pragma: no mutate
                            opts.append(f"Slot {i}: {ws.weapon.display_name}")  # pragma: no mutate
                        else:  # pragma: no mutate
                            opts.append(f"Slot {i}: Empty")  # pragma: no mutate
                    response = yield Ask(player, "Wield in which weapon slot?", opts)  # pragma: no mutate
                    ws = p.weapon_slots[response[player]]
                if ws.weapon is not None:
                    yield from do(Discard(player, ws.weapon, "wield old weapon"))(g)  # pragma: no mutate
                for kill_card in list(ws.killstack.cards):
                    yield from do(Discard(player, kill_card, "wield kill pile"))(g)  # pragma: no mutate
                ws.wield(card)
            case Disarm(player, source):
                p = g.players[player]
                for ws in p.weapon_slots:
                    if ws.weapon is not None:
                        yield from do(Discard(player, ws.weapon, "disarm weapon"))(g)  # pragma: no mutate
                    for kill_card in list(ws.killstack.cards):
                        yield from do(Discard(player, kill_card, "disarm kill pile"))(g)  # pragma: no mutate
            case TransferHP(player, target, amount, source):
                p = g.players[player]
                old_hp = p.hp
                yield from do(Damage(player, amount, source))(g)
                actual = old_hp - p.hp
                if actual > 0:
                    yield from do(Heal(target, actual, source))(g)
            case StealHP(player, target, amount, source):
                t = g.players[target]
                old_hp = t.hp
                yield from do(Damage(target, amount, source))(g)
                actual = old_hp - t.hp
                if actual > 0:
                    yield from do(Heal(player, actual, source))(g)
            case Resolve(resolver, card, source):
                from combat import resolve_combat
                if card.is_type(CardType.ENEMY):
                    yield from resolve_combat(resolver, card)(g)
                elif card.is_type(CardType.FOOD):
                    yield from do(Eat(resolver, card, "resolve food"))(g)  # pragma: no mutate
                elif card.is_type(CardType.WEAPON):
                    yield from do(Wield(resolver, card, "resolve weapon"))(g)  # pragma: no mutate
                elif card.is_type(CardType.EQUIPMENT):
                    yield from do(Equip(resolver, card, "resolve equipment"))(g)  # pragma: no mutate
                elif card.is_type(CardType.EVENT):
                    yield from do(Discard(resolver, card, "resolve event"))(g)  # pragma: no mutate
            case Eat(player, card, source):
                p = g.players[player]
                if not p.is_satiated:
                    assert card.level is not None
                    yield from do(Heal(player, card.level, "food"))(g)  # pragma: no mutate
                    p.is_satiated = True
                yield from do(Discard(player, card, "food consumed"))(g)  # pragma: no mutate
            case EndPhase(phase):
                pass
            case StartPhase(phase):
                pass
            case GameOver(result):
                g.game_result = result
            case FlipPriority():
                g.priority = other(g.priority)
            case _:  # pragma: no mutate
                raise Exception(f"Action not in list: {action}")  # pragma: no mutate
    return effect

def _player_to_choose_replacement(g: GameState, action: Action) -> PID:  # pragma: no mutate
    if isinstance(action, (Damage, Heal, SetHP)):  # pragma: no mutate
        return action.target  # pragma: no mutate
    return g.priority  # pragma: no mutate

def _fire_triggers(g: GameState, action: Action, kind: TKind) -> Negotiation:
    triggered = [ tr for tr in _get_triggers(g) if tr.kind == kind ]  # pragma: no mutate
    if not triggered:  # pragma: no mutate
        return  # pragma: no mutate

    if len(triggered) > 1:  # pragma: no mutate
        pid = _player_to_choose_replacement(g, action)  # pragma: no mutate
        response = yield Ask(pid, f"Order {kind} triggers for {action}:", [tr.name for tr in triggered])  # pragma: no mutate
        idx = response[pid]  # pragma: no mutate
        triggered.insert(0, triggered.pop(idx))  # pragma: no mutate

    for tr in triggered:  # pragma: no mutate
        yield from tr.callback(action)(g)  # pragma: no mutate

def _get_triggers(g: GameState) -> list[Trait]:
   return []  # pragma: no mutate
