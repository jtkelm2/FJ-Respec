import json
import logging
import socket
from abc import abstractmethod
from dataclasses import dataclass

from core.type import Option, PlayerView, PromptHalf
from interact.serial import Serializer

log = logging.getLogger("server")


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


@dataclass
class ScriptedPlayer(Player):
  script: list[Option]

  def push_state(self, view: PlayerView) -> None:
    pass

  def request(self, prompt_half: PromptHalf) -> Option:
    return self.script.pop(0)

  def notify(self, text: str) -> None:
    pass

  def close(self) -> None:
    pass


# ── JSON wire helpers ─────────────────────────────────────────

def _send(sock: socket.socket, msg: dict) -> None:
    data = json.dumps(msg) + "\n"
    sock.sendall(data.encode())

def _recv(sock: socket.socket) -> dict:
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return json.loads(buf.split(b"\n", 1)[0])


# ── TCPPlayer ─────────────────────────────────────────────────

class TCPPlayer(Player):
    """Server-side Player backed by a TCP socket."""

    def __init__(self, sock: socket.socket, label: str = "?", serializer: Serializer | None = None):
        self._sock = sock
        self._label = label
        self._serializer = serializer

    def push_state(self, view: PlayerView) -> None:
        log.debug("[%s] push_state (hp=%d, hand=%d, deck=%d)",
                  self._label, view.hp, len(view.hand), view.deck_size)
        assert self._serializer is not None
        view_data = self._serializer.player_view(view)
        _send(self._sock, {"type": "state", "view": view_data})

    def request(self, prompt_half: PromptHalf) -> Option:
        assert self._serializer is not None
        serialized_options = [self._serializer.option(o) for o in prompt_half.options]
        log.info("[%s] request: %r  options=%s",
                 self._label, prompt_half.text, serialized_options)
        _send(self._sock, {
            "type": "prompt",
            "text": prompt_half.text,
            "options": serialized_options,
        })
        msg = _recv(self._sock)
        chosen = msg["option"]
        # Find the engine Option that matches the returned serialized option
        for opt, ser_opt in zip(prompt_half.options, serialized_options):
            if ser_opt == chosen:
                log.info("[%s] response: %s", self._label, chosen)
                return opt
        raise ValueError(f"Client returned unknown option: {chosen}")

    def notify(self, text: str) -> None:
        log.info("[%s] notify: %s", self._label, text)
        _send(self._sock, {"type": "notify", "text": text})

    def close(self) -> None:
        log.info("[%s] close", self._label)
        _send(self._sock, {"type": "close"})
        self._sock.close()
