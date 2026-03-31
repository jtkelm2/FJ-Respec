from core.types import *

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
    # TODO: "Before X" triggers
    g_next = _apply_action(g,action) # TODO: "Instead of X, do Y"? Need to replace before "before X" triggers
    # TODO: "After X" triggers
    return g_next
    yield
  return effect

def compose(*effects) -> Effect:
  def composed(g: GameState) -> Generator[Prompt, Response, GameState]:
    g_next = g
    for eff in effects:
      g_next = yield from eff(g_next)
    return g_next
  return composed

def _apply_action(g:GameState, action:Action) -> GameState:
  match action:
    case SetHP(target, value, source):
      return g # TODO
    case Heal(target, amount, source):
      return g # TODO: in terms of SetHP
    case Damage(target, amount, source):
      return g # TODO: in terms of SetHP
    case _:
      raise Exception("Action not in list")