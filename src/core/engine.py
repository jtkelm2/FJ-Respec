from core.type import *


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
        g = yield from _fire_triggers(g, action, "before")

        # Execute
        _apply_action(g, action)

        # After triggers
        g = yield from _fire_triggers(g, action, "after")

        return g
    return effect

def compose(*effects) -> Effect:
    def composed(g: GameState) -> Generator[Prompt, Response, GameState]:
        for eff in effects:
            g = yield from eff(g)
        return g
    return composed

def _apply_action(g: GameState, action: Action) -> None:
    match action:
        case SetHP(target, value, source):
            p = g.players[target]
            new_hp = value
            if p.hp_floor is not None:
                new_hp = max(new_hp, p.hp_floor)
            if p.hp_ceiling is not None:
                new_hp = min(new_hp, p.hp_ceiling)
            p.hp = new_hp
        case Heal(target, amount, source):
            _apply_action(g, SetHP(target, g.players[target].hp + amount, source))
        case Damage(target, amount, source):
            _apply_action(g, SetHP(target, g.players[target].hp - amount, source))
        case _:
            raise Exception(f"Action not in list: {action}")

def _player_to_choose_replacement(g: GameState, action: Action) -> PID:
    if isinstance(action, (Damage, Heal, SetHP)):
        return action.target
    return g.priority

def _fire_triggers(
    g: GameState, action: Action, kind: str
) -> Generator[Prompt, Response, GameState]:
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