from core.type import *

def _get_listeners(g:GameState) -> list[Listener]:
    return [] # TODO

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
        # Instead-of: rewrite the action through replacement listeners
        action_final = yield from _apply_replacements(g, action)

        # Before: fire before the (possibly rewritten) action executes
        g = yield from _fire_triggers(g, action_final, "before")

        # Execute
        _apply_action(g, action_final)

        g = yield from _fire_triggers(g, action_final, "after")

        return g
    return effect

def compose(*effects) -> Effect:
    def composed(g: GameState) -> Generator[Prompt, Response, GameState]:
        for eff in effects:
            g = yield from eff(g)
        return g
    return composed

def _apply_action(g: GameState, action: Action):
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

def _apply_replacements(g: GameState, action: Action) -> Generator[Prompt, Response, Effect]:
    while True:
        applicable = [
            l for l in _get_listeners(g)
            if l.kind == "replacement"
            and l.callback(action) is not None
        ]
        if not applicable:
            break
        if len(applicable) == 1:
            chosen = applicable[0]
        else:
            pid = _player_to_choose_replacement(g,action)
            response = yield Ask(pid, f"Choose replacement for {action}:", [l.name for l in applicable])
            chosen = applicable[response[pid]]
        effect = chosen.callback(action)
    return effect

def _fire_triggers(
    g: GameState, action: Action, kind: str
) -> Generator[Prompt, Response, GameState]:
    triggered = [
        l for l in _get_listeners(g)
        if l.kind == kind and l.callback(action) is not None
    ]
    if not triggered:
        return g

    if len(triggered) > 1:
        pid = _player_to_choose_replacement(g, action)
        response = yield Ask(pid, f"Order {kind} triggers for {action}:", [l.name for l in triggered])
        idx = response[pid]
        triggered.insert(0, triggered.pop(idx))

    for l in triggered:
        g = yield from l.callback(action)(g)
    return g