from abc import abstractmethod

from core.type import *

# An Interpreter is the environment from which the engine gets responses to its prompts.
# A Player is an Interpreter's interface to one player.
# We can build an Interpreter by aggregating two Players.
#
# Players include human players (CLI), AI players, remote players, scripted players.

class Interpreter:
  @abstractmethod
  def interpret(self, prompt: Prompt) -> Response:
    pass

class Player:
  @abstractmethod
  def push_state(self, view: PlayerView) -> None:
    """Push updated visible state. Non-blocking."""
    pass

  @abstractmethod
  def request(self, prompt_half: PromptHalf) -> int:
    """Send a prompt and block until the player responds."""
    pass

  @abstractmethod
  def notify(self, text: str) -> None:
    """Send a non-interactive message. Non-blocking."""
    pass

  @abstractmethod
  def close(self) -> None:
    """Signal end of game and release resources."""
    pass

@dataclass
class AggregateInterpreter(Interpreter): # Sequential aggregation of two players; not intended for async composition
  i1:Player
  i2:Player

  def _route(self, pid: PID) -> Player:
    return self.i1 if pid == PID.RED else self.i2

  def interpret(self, prompt: Prompt) -> Response:
    match prompt.kind:
      case PKind.BOTH: return {pid: self._route(pid).request(prompt_half) for pid, prompt_half in prompt.for_player.items()}
      case PKind.EITHER:
        pid, prompt_half = next(iter(prompt.for_player.items()))
        return {pid: self._route(pid).request(prompt_half)}

class CLIInterpreter(Player):
  player_name: str

  def __init__(self,player_name:str | None = None):
    self.player_name = player_name or input("Your name? ")

  def push_state(self, view: PlayerView) -> None:
    pass

  def request(self, prompt_half: PromptHalf) -> int:
    print(f"\n[{self.player_name}] {prompt_half.text}")
    for i, opt in enumerate(prompt_half.options):
      print(f"  {i}: {opt}")
    return int(input("  > "))

  def notify(self, text: str) -> None:
    print(text)

  def close(self) -> None:
    pass

@dataclass
class ScriptedInterpreter(Player):
  script:list

  def push_state(self, view: PlayerView) -> None:
    pass

  def request(self, prompt_half: PromptHalf):
    return self.script.pop(0)

  def notify(self, text: str) -> None:
    pass

  def close(self) -> None:
    pass


# ── Abstract contracts ────────────────────────────────────────

class GameClient:
  """Client-side contract. Frontends implement this."""

  @abstractmethod
  def on_state(self, view: PlayerView) -> None:
    """Render updated visible game state.
    Game result is part of PlayerView — detect game over here."""
    pass

  @abstractmethod
  def on_prompt(self, text: str, options: list[str]) -> int:
    """Display a prompt and return the chosen option index."""
    pass

  @abstractmethod
  def on_notify(self, text: str) -> None:
    """Display a notification message."""
    pass


class GameServer:
  """Abstraction for hosting a game."""

  @abstractmethod
  def await_players(self) -> tuple[Player, Player]:
    """Wait for two players to connect. Returns (red, blue) players."""
    pass

  @abstractmethod
  def run_game(self, seed: int | None = None) -> GameResult:
    """Set up and run a complete game. Returns the result."""
    pass

  @abstractmethod
  def shutdown(self) -> None:
    """Release all resources."""
    pass
