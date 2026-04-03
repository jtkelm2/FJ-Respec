from abc import abstractmethod

from core.type import *

# An interpreter is a means of returning input from prompts.
# We can build one by aggregating many partial interpreters, where a
# partial interpreter is a means of returning input from per-player prompts.
#
# Partial interpreters include human players (textual or CLI), AI players, remote players, scripted players.

class Interpreter:
  @abstractmethod
  def interpret(self, prompt: Prompt) -> Response:
    pass

class PartialInterpreter:
  @abstractmethod
  def interpret(self, prompt_half: PromptHalf) -> int:
    pass

@dataclass
class AggregateInterpreter(Interpreter): # Sequential aggregation of two interpreters; not intended for async composition
  i1:PartialInterpreter
  i2:PartialInterpreter

  def _route(self, pid: PID) -> PartialInterpreter:
    return self.i1 if pid == PID.RED else self.i2

  def interpret(self, prompt: Prompt) -> Response:
    match prompt.kind:
      case PKind.BOTH: return {pid: self._route(pid).interpret(prompt_half) for pid, prompt_half in prompt.for_player.items()}
      case PKind.EITHER:
        pid, prompt_half = next(iter(prompt.for_player.items()))
        return {pid: self._route(pid).interpret(prompt_half)}

class CLIInterpreter(PartialInterpreter):
  player_name: str

  def __init__(self,player_name:str | None = None):
    self.player_name = player_name or input("Your name? ")

  def interpret(self, prompt_half: PromptHalf) -> int:
    print(f"\n[{self.player_name}] {prompt_half.text}")
    for i, opt in enumerate(prompt_half.options):
      print(f"  {i}: {opt}")
    return int(input("  > "))

@dataclass
class ScriptedInterpreter(PartialInterpreter):
  script:list

  def interpret(self, prompt_half: PromptHalf):
    return self.script.pop(0)