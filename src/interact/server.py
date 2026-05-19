"""
Server-side: GameServer contract, TCPGameServer.

A GameServer accepts pairs of Connections and runs a game per pair.
Many games may run concurrently in a single process; each game gets
its own thread, its own logger, and its own log file.

The game protocol (catalog, state pushing, prompt routing, forfeit on
disconnect/resign, close) lives in run_game(). Subclasses provide the
transport via accept_pair() and serve_forever() drives the accept loop.
"""

import datetime
import logging
import os
from abc import abstractmethod
from itertools import count
from logging import DEBUG, FileHandler, Formatter, getLogger
from socket import AF_INET, SO_REUSEADDR, SOCK_STREAM, SOL_SOCKET, socket
from threading import Lock, Thread

from core.type import PID, GameResult, Outcome
from interact.connection import Connection, TCPConnection
from interact.player import (
    Player, RemotePlayer, PidAssignment,
    Resigned, Disconnect, PlayerExited, OOB,
)
from interact.interpret import run, AsyncAggregateInterpreter, ViewPushingInterpreter
from interact.serial import Accumulator
from phase.game import game_loop
from phase.setup import create_initial_state

_root_log = getLogger("server")


# ── Forfeit watcher ──────────────────────────────────────────────

class ForfeitWatcher:
  """Per-game monitor: watches each player's OOB channel and aborts the
  game when any player resigns or disconnects.

  Spawns one daemon thread per player. The first game-ending OOB wins
  (recorded in `exited`); both players' prompts are then terminated so
  the game loop unwinds with PlayerExited."""

  def __init__(self, players: dict[PID, Player], logger: logging.Logger):
    self._players = players
    self._log = logger
    self._lock = Lock()
    self._stopped = False
    self.exited: dict[PID, OOB] = {}
    for pid in players:
      Thread(target=self._monitor, args=(pid,), daemon=True,
             name=f"watch-{pid.name}").start()

  def _monitor(self, pid: PID) -> None:
    while True:
      oob = self._players[pid].receive_oob()
      if self._stopped:
        return
      if isinstance(oob, (Resigned, Disconnect)):
        with self._lock:
          if self._stopped:
            return
          self.exited.setdefault(pid, oob)
          self._log.info("ForfeitWatcher: %s exited (%s)", pid.name, type(oob).__name__)
          self._stopped = True
          for p in self._players.values():
            p.terminate()
        return
      self._log.info("ForfeitWatcher: %s advisory OOB %s (ignored)",
                     pid.name, type(oob).__name__)

  def stop(self) -> None:
    """Signal the watcher to ignore further OOBs (game ended normally)."""
    self._stopped = True


def _forfeit_result(exited: dict[PID, OOB]) -> GameResult:
  """Survivors win; if both exited, no winner."""
  survivors = tuple(pid for pid in PID if pid not in exited)
  return GameResult(survivors, Outcome.FORFEIT)


# ── GameServer ───────────────────────────────────────────────────

class GameServer:
  """Abstraction for hosting games.

  Subclasses implement accept_pair() to yield Connection pairs and
  shutdown() to release transport resources. The protocol orchestration
  for a single game is handled by run_game(); serve_forever() loops on
  accept_pair() and spawns a thread per game."""

  def __init__(self, log_dir: str = "logs/server"):
    self._log_dir = log_dir
    self._next_id = count(1)
    self._id_lock = Lock()

  @abstractmethod
  def accept_pair(self) -> tuple[Connection, Connection]:
    """Block until two players have connected and been paired."""
    pass

  @abstractmethod
  def shutdown(self) -> None:
    """Release all transport resources."""
    pass

  def _allocate_game_id(self) -> str:
    with self._id_lock:
      return str(next(self._next_id))

  def _make_game_logger(self, game_id: str) -> logging.Logger:
    """One log file per game. Per-game logger does not propagate, so the
    shared 'server' root logger stays untouched and lines from concurrent
    games do not interleave in a shared file."""
    os.makedirs(self._log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(self._log_dir, f"game-{game_id}-{ts}.log")
    logger = logging.getLogger(f"server.game-{game_id}")
    logger.setLevel(DEBUG)
    logger.propagate = False
    # Clear stale handlers if a game id is reused (defensive).
    for h in list(logger.handlers):
      logger.removeHandler(h)
    handler = FileHandler(path, mode="w")
    handler.setFormatter(Formatter(
      "%(asctime)s %(levelname)-5s %(threadName)s %(message)s",
      datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger

  def run_game(self, pair: tuple[Connection, Connection],
               seed: int | None = None,
               game_id: str | None = None) -> GameResult:
    """Run a single game over a Connection pair. Returns the final GameResult.

    Forfeit (disconnect or resign) yields GameResult(survivors, FORFEIT)."""
    red_conn, blue_conn = pair
    gid = game_id or self._allocate_game_id()
    log = self._make_game_logger(gid)
    log.info("game %s starting", gid)
    _root_log.info("game %s starting", gid)

    g = create_initial_state(seed=seed)
    acc = Accumulator(g)
    serializer = acc.serializer()

    red = RemotePlayer(red_conn, serializer, PID.RED, "RED", logger=log)
    blue = RemotePlayer(blue_conn, serializer, PID.BLUE, "BLUE", logger=log)
    players: dict[PID, Player] = {PID.RED: red, PID.BLUE: blue}

    catalog_msg = {"type": "catalog", **acc.catalog()}
    red.send(catalog_msg)
    blue.send(catalog_msg)
    red.notify(PidAssignment(PID.RED))
    blue.notify(PidAssignment(PID.BLUE))

    watcher = ForfeitWatcher(players, log)
    interp = ViewPushingInterpreter(
      g, players, AsyncAggregateInterpreter(red, blue, logger=log), logger=log,
    )

    try:
      run(g, game_loop(), interp)
    except PlayerExited:
      log.info("game %s: forfeit (exited=%s)", gid,
               {pid.name: type(o).__name__ for pid, o in watcher.exited.items()})
      g.game_result = _forfeit_result(watcher.exited)

    watcher.stop()
    for pid in PID:
      interp.push_if_changed(pid)
      players[pid].close()

    log.info("game %s ended: %s", gid, g.game_result)
    _root_log.info("game %s ended: %s", gid, g.game_result)
    # Close per-game handlers so files flush and don't leak fds.
    for h in list(log.handlers):
      log.removeHandler(h)
      h.close()

    assert g.game_result is not None
    return g.game_result

  def serve_forever(self, seed: int | None = None) -> None:
    """Accept pairs in a loop; run each game in its own thread.

    Returns only when accept_pair() raises (e.g. listener closed)."""
    while True:
      try:
        pair = self.accept_pair()
      except OSError as e:
        _root_log.info("serve_forever: accept loop stopped (%s)", e)
        return
      gid = self._allocate_game_id()
      Thread(
        target=self.run_game, args=(pair,), kwargs={"seed": seed, "game_id": gid},
        daemon=False, name=f"game-{gid}",
      ).start()


# ── TCPGameServer ─────────────────────────────────────────────────

class TCPGameServer(GameServer):
  """TCP-backed GameServer: every two incoming connections form a game.

  The listener socket is opened once and reused for the lifetime of the
  server; only the per-pair accept calls are made by accept_pair()."""

  def __init__(self, host: str = "0.0.0.0", port: int = 9000,
               log_dir: str = "logs/server"):
    super().__init__(log_dir=log_dir)
    self._host = host
    self._port = port
    self._server_sock: socket | None = None
    self._accept_lock = Lock()  # serializes the two accept()s of a single pair

  def _ensure_listening(self) -> socket:
    if self._server_sock is None:
      s = socket(AF_INET, SOCK_STREAM)
      s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
      s.bind((self._host, self._port))
      s.listen()
      _root_log.info("Listening on %s:%d ...", self._host, self._port)
      self._server_sock = s
    return self._server_sock

  def accept_pair(self) -> tuple[Connection, Connection]:
    server_sock = self._ensure_listening()
    with self._accept_lock:
      red_sock, red_addr = server_sock.accept()
      _root_log.info("RED connected from %s", red_addr)
      blue_sock, blue_addr = server_sock.accept()
      _root_log.info("BLUE connected from %s", blue_addr)
    return TCPConnection(red_sock), TCPConnection(blue_sock)

  def shutdown(self) -> None:
    if self._server_sock is not None:
      self._server_sock.close()
      self._server_sock = None


# ── Entrypoint ────────────────────────────────────────────────────

def _setup_root_logging():
  """Lifetime-of-process log for the accept loop and cross-game events.
  Per-game messages go to per-game files via 'server.game-<id>'."""
  os.makedirs("logs/server", exist_ok=True)
  ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
  filename = f"logs/server/server-{ts}.log"
  handler = FileHandler(filename, mode="w")
  handler.setFormatter(Formatter(
    "%(asctime)s %(levelname)-5s %(threadName)s %(message)s", datefmt="%H:%M:%S"
  ))
  _root_log.addHandler(handler)
  _root_log.setLevel(DEBUG)


if __name__ == "__main__":
  import sys
  port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
  _setup_root_logging()
  server = TCPGameServer(port=port)
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    _root_log.info("interrupted, shutting down")
    print("shutting down")
  finally:
    server.shutdown()
