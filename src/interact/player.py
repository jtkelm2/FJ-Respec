from abc import abstractmethod
from dataclasses import dataclass
from logging import Logger, getLogger
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

_default_log = getLogger("server")


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


class PlayerExited(Exception):
    """Raised by Player.prompt() when the player has resigned or disconnected.

    The exception is a wake-up signal; the *cause* of the forfeit is recorded
    out of band (see ForfeitWatcher). Whichever side triggers this — the player
    themselves, or an external terminate() call from a watcher — is irrelevant
    to the caller, which should treat the game as forfeit."""


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

  def terminate(self) -> None:
    """Externally abort any pending prompt with PlayerExited.

    Called by ForfeitWatcher when the *other* player exits, so a prompt
    pending on this player wakes up. Default is no-op (e.g. ScriptedPlayer
    never has a pending wire prompt to abort)."""
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

_ABORT = object()  # sentinel: injected into _option_queue to wake a pending prompt()


class RemotePlayer(Player):
  """Player backed by a Connection and Serializer.

  An internal listener thread reads messages from the connection
  and dispatches them to either _option_queue or _oob_queue based
  on message type. prompt() is interruptible via terminate()."""

  def __init__(self, conn: Connection, serializer: Serializer, pid: PID,
               label: str = "?", logger: Logger | None = None):
    self._conn = conn
    self._serializer = serializer
    self._pid = pid
    self._label = label
    self._log = logger or _default_log
    self._last_options: list[Option] = []
    self._option_queue: Queue[Option | list[Option] | object] = Queue()
    self._oob_queue: Queue[OOB] = Queue()
    self._aborted = Event()
    self._listener = Thread(target=self._listen, daemon=True, name=f"recv-{label}")
    self._listener.start()

  def send(self, msg: dict) -> None:
    """Send a raw protocol message over the wire. Used for messages that
    don't fit the typed Player contract (e.g. catalog)."""
    self._log.info("[%s] >>> %s", self._label, msg)
    self._conn.send(msg)

  def _listen(self) -> None:
    try:
      while True:
        msg = self._conn.recv()
        self._log.info("[%s] <<< %s", self._label, msg)
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
            self._log.warning("[%s] unknown message type: %s", self._label, msg.get("type"))
    except (ConnectionError, OSError):
      self._log.info("[%s] connection closed", self._label)
      self._oob_queue.put(Disconnect())

  def push_state(self, view: PlayerView, events: list | None = None) -> None:
    try:
      self.send(self._serializer.state_message(view, self._pid, events))
    except (ConnectionError, OSError) as e:
      self._log.info("[%s] push_state suppressed: %s", self._label, e)

  def prompt(self, prompt_half: PromptHalf) -> Option | list[Option]:
    if self._aborted.is_set():
      raise PlayerExited()
    self._last_options = list(prompt_half.options)
    try:
      self.send(self._serializer.prompt_message(prompt_half))
    except (ConnectionError, OSError):
      raise PlayerExited()
    result = self._option_queue.get()
    if result is _ABORT:
      raise PlayerExited()
    return result  # type: ignore[return-value]

  def receive_oob(self) -> OOB:
    return self._oob_queue.get()

  def notify(self, notification: Notification) -> None:
    try:
      self.send(notify_message(notification))
    except (ConnectionError, OSError) as e:
      self._log.info("[%s] notify suppressed: %s", self._label, e)

  def terminate(self) -> None:
    """Wake any pending prompt() with PlayerExited. Idempotent."""
    if not self._aborted.is_set():
      self._aborted.set()
      self._option_queue.put(_ABORT)

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
