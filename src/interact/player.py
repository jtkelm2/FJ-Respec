import json
import logging
import socket
from abc import abstractmethod

from core.type import Option, PlayerView, PromptHalf
from interact.serial import Serializer, ClientOption

log = logging.getLogger("server")


# ── Player contract ──────────────────────────────────────────

class Player:
  @abstractmethod
  def push_state(self, view: PlayerView) -> None:
    """Push updated visible state. Non-blocking."""
    pass

  @abstractmethod
  def request(self, prompt_half: PromptHalf) -> Option:
    """Send a prompt and block until the player responds with a chosen Option."""
    pass

  @abstractmethod
  def notify(self, text: str) -> None:
    """Send a non-interactive message. Non-blocking."""
    pass

  @abstractmethod
  def close(self) -> None:
    """Signal end of game and release resources."""
    pass


# ── ScriptedPlayer ───────────────────────────────────────────

class ScriptedPlayer(Player):
  """Test double: pops Options from a pre-built script."""

  def __init__(self, script: list[Option]):
    self.script = script

  def push_state(self, view: PlayerView) -> None:
    pass

  def request(self, prompt_half: PromptHalf) -> Option:
    return self.script.pop(0)

  def notify(self, text: str) -> None:
    pass

  def close(self) -> None:
    pass


# ── Connection contract ──────────────────────────────────────

class Connection:
  """Abstract wire connection. Used by RemotePlayer and AsyncAggregateInterpreter."""

  @abstractmethod
  def send(self, msg: dict) -> None:
    """Send a JSON-serializable message."""
    pass

  @abstractmethod
  def recv(self) -> dict:
    """Block until a message arrives. Returns parsed dict."""
    pass

  @abstractmethod
  def close(self) -> None:
    pass


class TCPConnection(Connection):
  """Connection backed by a TCP socket with line-delimited JSON."""

  def __init__(self, sock: socket.socket):
    self._sock = sock

  def send(self, msg: dict) -> None:
    data = json.dumps(msg) + "\n"
    self._sock.sendall(data.encode())

  def recv(self) -> dict:
    buf = b""
    while b"\n" not in buf:
      chunk = self._sock.recv(4096)
      if not chunk:
        raise ConnectionError("connection closed")
      buf += chunk
    return json.loads(buf.split(b"\n", 1)[0])

  def close(self) -> None:
    self._sock.close()


# ── RemotePlayer ─────────────────────────────────────────────

class RemotePlayer(Player):
    """Player backed by a Connection and Serializer."""

    def __init__(self, conn: Connection, serializer: Serializer, label: str = "?"):
        self._conn = conn
        self._serializer = serializer
        self._label = label
        self._last_options: list[Option] = []

    @property
    def conn(self) -> Connection:
        return self._conn

    def push_state(self, view: PlayerView) -> None:
        log.debug("[%s] push_state (hp=%d, hand=%d, deck=%d)",
                  self._label, view.hp, len(view.hand), view.deck_size)
        self._conn.send({"type": "state", "view": self._serializer.player_view(view)})

    def request(self, prompt_half: PromptHalf) -> Option:
        self._last_options = list(prompt_half.options)
        serialized_options = [self._serializer.option(o) for o in prompt_half.options]
        log.info("[%s] request: %r  options=%s",
                 self._label, prompt_half.text, serialized_options)
        self._conn.send({
            "type": "prompt",
            "text": prompt_half.text,
            "options": serialized_options,
        })
        # Block for response, handling OOB messages inline
        while True:
            msg = self._conn.recv()
            match msg["type"]:
                case "response":
                    chosen = msg["option"]
                    log.info("[%s] response: %s", self._label, chosen)
                    return self._resolve_option(chosen)
                case "resign":
                    log.info("[%s] resign (during request)", self._label)
                    # TODO: handle via game termination
                case "draw":
                    log.info("[%s] offer_draw (during request)", self._label)
                    # TODO: forward to other player
                case _:
                    raise ValueError(f"Unknown message type: {msg['type']}")

    def notify(self, text: str) -> None:
        log.info("[%s] notify: %s", self._label, text)
        self._conn.send({"type": "notify", "text": text})

    def close(self) -> None:
        log.info("[%s] close", self._label)
        self._conn.send({"type": "close"})
        self._conn.close()

    def _resolve_option(self, serialized: ClientOption) -> Option:
        for opt in self._last_options:
            if self._serializer.option(opt) == serialized:
                return opt
        raise ValueError(f"Client returned unknown option: {serialized}")
