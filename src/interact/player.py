from abc import abstractmethod
from dataclasses import dataclass
from logging import getLogger
from queue import Queue
from threading import Event, Thread

from core.type import Option, PID, PlayerView, PromptHalf
from interact.connection import Connection
from interact.serial import (
    Serializer, ClientOption,
    Info, PidAssignment, Notification, notify_message,
)

# Re-exported so callers can still `from interact.player import Info, PidAssignment, Notification`.
_ = (Info, PidAssignment, Notification, notify_message)

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


# ── Player contract ──────────────────────────────────────────

class Player:
  """Abstract player."""

  @abstractmethod
  def push_state(self, view: PlayerView, events: list | None = None) -> None:
    """Push updated visible state with events since last push. Non-blocking."""
    pass

  @abstractmethod
  def prompt(self, prompt_half: PromptHalf) -> Option | list[Option]:
    """Send a prompt and block until the player responds.

    Returns a single Option when `prompt_half.must_select == 1`, otherwise a
    list[Option] of length exactly `must_select`."""
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

  def push_state(self, view: PlayerView, events: list | None = None) -> None:
    pass

  def prompt(self, prompt_half: PromptHalf) -> Option | list[Option]:
    n = prompt_half.must_select
    if n == 1:
      return self.script.pop(0)
    return [self.script.pop(0) for _ in range(n)]

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
    self._option_queue: Queue[Option | list[Option]] = Queue()
    self._oob_queue: Queue[OOB] = Queue()
    self._listener = Thread(target=self._listen, daemon=True, name=f"recv-{label}")
    self._listener.start()

  def send(self, msg: dict) -> None:
    """Send a raw protocol message over the wire. Used for messages that
    don't fit the typed Player contract (e.g. catalog)."""
    log.info("[%s] >>> %s", self._label, msg)
    self._conn.send(msg)

  def _listen(self) -> None:
    try:
      while True:
        msg = self._conn.recv()
        log.info("[%s] <<< %s", self._label, msg)
        match msg.get("type"):
          case "response":
            if "options" in msg:
              self._option_queue.put([self._resolve_option(o) for o in msg["options"]])
            else:
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

  def push_state(self, view: PlayerView, events: list | None = None) -> None:
    self.send(self._serializer.state_message(view, self._pid, events))

  def prompt(self, prompt_half: PromptHalf) -> Option | list[Option]:
    self._last_options = list(prompt_half.options)
    self.send(self._serializer.prompt_message(prompt_half))
    return self._option_queue.get()

  def receive_oob(self) -> OOB:
    return self._oob_queue.get()

  def notify(self, notification: Notification) -> None:
    self.send(notify_message(notification))

  def close(self) -> None:
    try:
      self.send({"type": "close"})
    except (ConnectionError, OSError):
      pass
    self._conn.close()

  def _resolve_option(self, serialized: ClientOption) -> Option:
    for opt in self._last_options:
      if self._serializer.option(opt) == serialized:
        return opt
    raise ValueError(f"Unknown option: {serialized}")
