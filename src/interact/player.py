from abc import abstractmethod
from dataclasses import dataclass
from logging import getLogger
from queue import Queue
from threading import Event, Thread

from core.type import Option, PID, PlayerView, PromptHalf
from interact.connection import Connection
from interact.serial import Serializer, ClientOption

log = getLogger("server")


# ── OOB types ────────────────────────────────────────────────

@dataclass
class Resigned:
    pass

@dataclass
class DrawOffered:
    pass

@dataclass
class DrawAccepted:
    pass

@dataclass
class Disconnect:
    pass

OOB = Resigned | DrawOffered | DrawAccepted | Disconnect


# ── Notification types ───────────────────────────────────────

@dataclass
class RoleAssignment:
    role: str    # e.g. "Human", "???"
    side: PID    # RED or BLUE

@dataclass
class Info:
    text: str

Notification = RoleAssignment | Info


# ── Player contract ──────────────────────────────────────────

class Player:
  """Abstract player."""

  @abstractmethod
  def push_state(self, view: PlayerView) -> None:
    """Push updated visible state. Non-blocking."""
    pass

  @abstractmethod
  def prompt(self, prompt_half: PromptHalf) -> Option:
    """Send a prompt and block until the player responds with a chosen Option."""
    pass

  @abstractmethod
  def receive_oob(self) -> OOB:
    """Block until an out-of-band event arrives (resignation, draw offer, etc.)."""
    pass

  @abstractmethod
  def notify(self, notification: Notification) -> None:
    """Send a non-interactive notification. Non-blocking."""
    pass

  @abstractmethod
  def close(self) -> None:
    """Signal end of game and release resources."""
    pass


# ── ScriptedPlayer ───────────────────────────────────────────

class ScriptedPlayer(Player):
  """Test double: pops Options from a pre-built script."""

  def __init__(self, script: list[Option]):
    self.script: list[Option] = list(script)
    self._never = Event()

  def push_state(self, view: PlayerView) -> None:
    pass

  def prompt(self, prompt_half: PromptHalf) -> Option:
    return self.script.pop(0)

  def receive_oob(self) -> OOB:
    self._never.wait()
    raise RuntimeError("unreachable")  # pragma: no mutate

  def notify(self, notification: Notification) -> None:
    pass

  def close(self) -> None:
    pass


# ── RemotePlayer ─────────────────────────────────────────────

class RemotePlayer(Player):
  """Player backed by a Connection and Serializer.

  An internal listener thread reads messages from the connection
  and dispatches them to either _option_queue or _oob_queue based
  on message type."""

  def __init__(self, conn: Connection, serializer: Serializer, pid: PID, label: str = "?"):
    self._conn = conn
    self._serializer = serializer
    self._pid = pid
    self._label = label
    self._last_options: list[Option] = []
    self._option_queue: Queue[Option] = Queue()
    self._oob_queue: Queue[OOB] = Queue()
    self._listener = Thread(target=self._listen, daemon=True, name=f"recv-{label}")
    self._listener.start()

  def _listen(self) -> None:
    try:
      while True:
        msg = self._conn.recv()
        match msg.get("type"):
          case "response":
            self._option_queue.put(self._resolve_option(msg["option"]))
          case "resign":
            self._oob_queue.put(Resigned())
          case "draw_offer":
            self._oob_queue.put(DrawOffered())
          case "draw_accept":
            self._oob_queue.put(DrawAccepted())
          case _:
            log.warning("[%s] unknown message type: %s", self._label, msg.get("type"))
    except (ConnectionError, OSError):
      log.info("[%s] connection closed", self._label)
      self._oob_queue.put(Disconnect())

  def push_state(self, view: PlayerView) -> None:
    log.debug("[%s] push_state (hp=%d, hand=%d, deck=%d)",
              self._label, view.hp, len(view.hand), view.deck_size)
    self._conn.send({"type": "state", "view": self._serializer.player_view(view, self._pid)})

  def prompt(self, prompt_half: PromptHalf) -> Option:
    self._last_options = list(prompt_half.options)
    serialized_options = [self._serializer.option(o) for o in prompt_half.options]
    log.info("[%s] prompt: %r  options=%s",
             self._label, prompt_half.text, serialized_options)
    self._conn.send({
      "type": "prompt",
      "text": prompt_half.text,
      "options": serialized_options,
    })
    return self._option_queue.get()

  def receive_oob(self) -> OOB:
    return self._oob_queue.get()

  def notify(self, notification: Notification) -> None:
    match notification:
      case RoleAssignment(role, side):
        msg = {"type": "notify", "kind": "role_assignment", "role": role, "side": side.name}
      case Info(text):
        msg = {"type": "notify", "kind": "info", "text": text}
    log.info("[%s] notify: %s", self._label, msg)
    self._conn.send(msg)

  def close(self) -> None:
    log.info("[%s] close", self._label)
    try:
      self._conn.send({"type": "close"})
    except (ConnectionError, OSError):
      pass
    self._conn.close()

  def _resolve_option(self, serialized: ClientOption) -> Option:
    for opt in self._last_options:
      if self._serializer.option(opt) == serialized:
        return opt
    raise ValueError(f"Unknown option: {serialized}")
