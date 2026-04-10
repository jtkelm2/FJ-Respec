"""
Connection abstraction: transport-agnostic message passing.

A Connection is an ordered, reliable, bidirectional message channel.
Messages are JSON-serializable dicts. The transport (TCP, WebSocket,
in-process pipe, etc.) is an implementation detail.
"""

import json
from abc import abstractmethod
from socket import AF_INET, SOCK_STREAM, socket


class Connection:
  """Abstract wire connection."""

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

  def __init__(self, sock: socket):
    self._sock = sock
    self._buf = b""

  @staticmethod
  def connect(host: str, port: int):
    """Open a TCP connection to the given host and port."""
    sock = socket(AF_INET, SOCK_STREAM)
    sock.connect((host, port))
    return TCPConnection(sock)

  def send(self, msg: dict) -> None:
    data = json.dumps(msg) + "\n"
    self._sock.sendall(data.encode())

  def recv(self) -> dict:
    while b"\n" not in self._buf:
      chunk = self._sock.recv(4096)
      if not chunk:
        raise ConnectionError("connection closed")
      self._buf += chunk
    line, self._buf = self._buf.split(b"\n", 1)
    return json.loads(line)

  def close(self) -> None:
    self._sock.close()
