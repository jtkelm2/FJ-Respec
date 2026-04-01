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
  def interpret(self, ask: Ask) -> int:
    pass

@dataclass
class AggregateInterpreter(Interpreter):
  i1:PartialInterpreter
  i2:PartialInterpreter
  
  def interpret(self, prompt: Prompt) -> Response:
    response = {}
    if isinstance(prompt,AskBoth):
      response[PID.RED]  = self.i1.interpret(prompt.only(PID.RED))
      response[PID.BLUE] = self.i2.interpret(prompt.only(PID.BLUE))
    if isinstance(prompt,Ask):
      match prompt.pid:
        case PID.RED:  response[PID.RED] =  self.i1.interpret(prompt)
        case PID.BLUE: response[PID.BLUE] = self.i2.interpret(prompt)
      response[other(prompt.pid)] = -1
    return response

class CLIInterpreter(PartialInterpreter):
  def interpret(self, ask: Ask) -> int:
    print(f"\n[Player {ask.pid}] {ask.text}")
    for i, opt in enumerate(ask.options):
      print(f"  {i}: {opt}")
    return int(input("  > "))

@dataclass
class ScriptedInterpreter(PartialInterpreter):
  script:list

  def interpret(self, ask: Ask):
    return self.script.pop(0)