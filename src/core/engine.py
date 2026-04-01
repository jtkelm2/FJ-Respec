from type import *
from interpret import *


def run(g:GameState, effect: Effect, i:Interpreter) -> GameState:
  e = effect(g)
  try:
    prompt = next(e)
    while True:
      response = i.interpret(prompt)
      prompt = e.send(response)
  except StopIteration as e:
    return e.value

def do(action: Action) -> Effect:
    def effect(g: GameState) -> Generator[Prompt, Response, GameState]:
        # Instead-of: find an applicable replacement and delegate to it.
        candidates = [ tr for tr in _get_traits(g) if tr.kind == TKind.REPLACEMENT ]
        if candidates:
          if len(candidates) == 1:
            chosen = candidates[0]
          else:
            pid = _player_to_choose_replacement(g, action)
            response = yield Ask(pid, f"Choose replacement for {action}:", [tr.name for tr in candidates])
            chosen = candidates[response[pid]]
          g = yield from chosen.callback(action)(g)
          return g

        # Before triggers
        g = yield from _fire_triggers(g, action, TKind.BEFORE)

        # Execute
        g = yield from _apply_action(action)(g)

        # After triggers
        g = yield from _fire_triggers(g, action, TKind.AFTER)

        return g
    return effect

################## Helpers #########

def _apply_action(action: Action) -> Effect:
    def effect(g:GameState) -> Generator[Prompt,Response,GameState]:
        match action:
            case Death(target):
                p = g.players[target]
                p.is_dead = True
            case Discard(discarder, card, source):
                p = g.players[discarder]
                g.deslot(card)
                p.discard.slot(card)
            case Slay(slayer, enemy, ws, source):
                if ws is None:
                   g = yield from do(Discard(slayer, enemy, "combat (fists)"))(g)
                   return g
                g.deslot(enemy)
                ws.killstack.slot(enemy)
            case SetHP(target, value, source):
                p = g.players[target]
                new_hp = value
                if p.hp_floor is not None:
                    new_hp = max(new_hp, p.hp_floor)
                if p.hp_ceiling is not None:
                    new_hp = min(new_hp, p.hp_ceiling)
                p.hp = new_hp
                if p.hp <= 0:
                    g = yield from do(Death(target))(g)
            case Heal(target, amount, source):
                g = yield from _apply_action(SetHP(target, g.players[target].hp + amount, source))(g) # TODO: Listeners for healing and damage
            case Damage(target, amount, source):
                g = yield from _apply_action(SetHP(target, g.players[target].hp - amount, source))(g)
            case _:
                raise Exception(f"Action not in list: {action}")
        return g
    return effect

def _player_to_choose_replacement(g: GameState, action: Action) -> PID:
    if isinstance(action, (Damage, Heal, SetHP)):
        return action.target
    return g.priority

def _fire_triggers(g: GameState, action: Action, kind: TKind) -> Generator[Prompt, Response, GameState]:
    triggered = [ tr for tr in _get_traits(g) if tr.kind == kind ]
    if not triggered:
        return g

    if len(triggered) > 1:
        pid = _player_to_choose_replacement(g, action)
        response = yield Ask(pid, f"Order {kind} triggers for {action}:", [tr.name for tr in triggered])
        idx = response[pid]
        triggered.insert(0, triggered.pop(idx)) # TODO : Ask for and apply actual permutation

    for tr in triggered:
        g = yield from tr.callback(action)(g)
    return g

def _get_traits(g: GameState) -> list[Trait]:
   raise Exception("TODO")