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


class CLIInterpreter(Player):
  player_name: str

  def __init__(self,player_name:str | None = None):
    self.player_name = player_name or input("Your name? ")

  def push_state(self, view: PlayerView) -> None:
    pass

  def request(self, prompt_half: PromptHalf) -> Option:
    print(f"\n[{self.player_name}] {prompt_half.text}")
    for i, opt in enumerate(prompt_half.options):
      print(f"  {i}: {opt}")
    return prompt_half.options[int(input("  > "))]

  def notify(self, text: str) -> None:
    print(text)

  def close(self) -> None:
    pass


@dataclass
class ScriptedInterpreter(Player):
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
        log.info("[%s] request: %r  options=%s",
                 self._label, prompt_half.text, prompt_half.options)
        _send(self._sock, {
            "type": "prompt",
            "text": prompt_half.text,
            "options": [str(o) for o in prompt_half.options],
        })
        msg = _recv(self._sock)
        choice = msg["choice"]
        log.info("[%s] response: %d (%s)",
                 self._label, choice, prompt_half.options[choice] if choice < len(prompt_half.options) else "?")
        return prompt_half.options[choice]

    def notify(self, text: str) -> None:
        log.info("[%s] notify: %s", self._label, text)
        _send(self._sock, {"type": "notify", "text": text})

    def close(self) -> None:
        log.info("[%s] close", self._label)
        _send(self._sock, {"type": "close"})
        self._sock.close()
