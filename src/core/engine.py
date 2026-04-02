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
        candidates = [ tr for tr in _get_triggers(g) if tr.kind == TKind.REPLACEMENT ]
        if candidates:
          if len(candidates) == 1:
            chosen = candidates[0]
          else:
            pid = _player_to_choose_replacement(g, action)
            response = yield Ask(pid, f"Choose replacement for {action}:", [tr.name for tr in candidates])
            chosen = candidates[response[pid]]
          yield from chosen.callback(action)(g)
          return

        # Before triggers
        yield from _fire_triggers(g, action, TKind.BEFORE)

        # Execute
        yield from _apply_action(action)(g)

        # After triggers
        yield from _fire_triggers(g, action, TKind.AFTER)
    return effect

################## Helpers #########

def _apply_action(action: Action) -> Effect:
    def effect(g:GameState) -> Negotiation:
        match action:
            case Death(target):
                p = g.players[target]
                p.is_dead = True
            case Discard(discarder, card, source):
                yield from do(SlotCard(card, g.players[discarder].discard, "discard"))(g)
            case Slay(slayer, enemy, ws, source):
                if ws is None:
                   yield from do(Discard(slayer, enemy, "combat (fists)"))(g)
                   return
                yield from do(SlotCard(enemy, ws.killstack, "slay"))(g)
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
                yield from do(SetHP(target, g.players[target].hp + amount, source))(g)
            case Damage(target, amount, source):
                yield from do(SetHP(target, g.players[target].hp - amount, source))(g)
            case Shuffle(slot, source):
                g.shuffle(slot)
            case ShuffleRefreshIntoDeck(player, source):
                p = g.players[player]
                yield from do(Slot2SlotAll(p.refresh, p.deck, "shuffle refresh"))(g)
                yield from do(Shuffle(p.deck, "shuffle refresh"))(g)
            case EnsureDeck(player, source):
                p = g.players[player]
                if p.deck.is_empty():
                    yield from do(ShuffleRefreshIntoDeck(player, "exhaustion recovery"))(g)
                if p.deck.is_empty():
                    for pid in PID:
                        yield from do(Death(pid, source="exhaustion"))(g)
            case Draw(player):
                yield from do(EnsureDeck(other(player),"draw to hand"))(g)
                yield from do(Slot2Slot(g.players[other(player)].deck, g.players[player].hand, "draw"))(g)
            case DealToActionField(player, card, slot):
                yield from do(SlotCard(card, slot, "deal to action field"))(g)
            case FlipPriority():
                g.priority = other(g.priority)
            case _:
                raise Exception(f"Action not in list: {action}")
    return effect

def _player_to_choose_replacement(g: GameState, action: Action) -> PID:
    if isinstance(action, (Damage, Heal, SetHP)):
        return action.target
    return g.priority

def _fire_triggers(g: GameState, action: Action, kind: TKind) -> Negotiation:
    triggered = [ tr for tr in _get_triggers(g) if tr.kind == kind ]
    if not triggered:
        return

    if len(triggered) > 1:
        pid = _player_to_choose_replacement(g, action)
        response = yield Ask(pid, f"Order {kind} triggers for {action}:", [tr.name for tr in triggered])
        idx = response[pid]
        triggered.insert(0, triggered.pop(idx)) # TODO : Ask for and apply actual permutation

    for tr in triggered:
        yield from tr.callback(action)(g)

def _get_triggers(g: GameState) -> list[Trait]:
   return [] # TODO: collect traits from players, cards, etc.