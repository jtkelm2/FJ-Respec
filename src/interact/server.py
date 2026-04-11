"""
Server-side: GameServer contract, TCPGameServer.

The game protocol (catalog, state pushing, prompt routing, close) lives
in GameServer.run_game() as a default method. Subclasses provide
connections via accept_connections(). Transport is an implementation detail.
"""

from abc import abstractmethod
from logging import DEBUG, FileHandler, Formatter, getLogger
from socket import AF_INET, SO_REUSEADDR, SOCK_STREAM, SOL_SOCKET, socket

from core.type import PID, GameResult
from interact.connection import Connection, TCPConnection
from interact.player import Player, RemotePlayer, RoleAssignment
from interact.interpret import run, AsyncAggregateInterpreter, ViewPushingInterpreter
from interact.serial import Accumulator
from phase.game import game_loop
from phase.setup import create_initial_state

log = getLogger("server")


class GameServer:
  """Abstraction for hosting a game.

  Subclasses implement accept_connections() to provide a pair of
  Connections. The protocol orchestration is handled by run_game()."""

  @abstractmethod
  def accept_connections(self) -> tuple[Connection, Connection]:
    """Block until two players connect. Returns (red_conn, blue_conn)."""
    pass

  @abstractmethod
  def shutdown(self) -> None:
    """Release all resources."""
    pass

  def run_game(self, seed: int | None = None) -> GameResult:
    """Set up and run a complete game over two Connections."""
    red_conn, blue_conn = self.accept_connections()
    g = create_initial_state(seed=seed)

    acc = Accumulator(g)
    serializer = acc.serializer()

    red_conn.send({"type": "catalog", **acc.catalog(PID.RED)})
    blue_conn.send({"type": "catalog", **acc.catalog(PID.BLUE)})

    red = RemotePlayer(red_conn, serializer, PID.RED, "RED")
    blue = RemotePlayer(blue_conn, serializer, PID.BLUE, "BLUE")

    red.notify(RoleAssignment(g.players[PID.RED].role.name, PID.RED))
    blue.notify(RoleAssignment(g.players[PID.BLUE].role.name, PID.BLUE))

    players: dict[PID, Player] = {PID.RED: red, PID.BLUE: blue}
    interp = ViewPushingInterpreter(g, players, AsyncAggregateInterpreter(red, blue))
    run(g, game_loop(), interp)

    # Push final state (includes game_result) then close
    for pid in PID:
        interp.push_if_changed(pid)
        players[pid].close()

    assert g.game_result is not None
    return g.game_result


class TCPGameServer(GameServer):

    def __init__(self, host: str = "0.0.0.0", port: int = 9000):
        self._host = host
        self._port = port
        self._server_sock: socket | None = None

    def accept_connections(self) -> tuple[Connection, Connection]:
        self._server_sock = socket(AF_INET, SOCK_STREAM)
        self._server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(2)
        log.info("Listening on %s:%d ...", self._host, self._port)

        red_sock, red_addr = self._server_sock.accept()
        log.info("RED connected from %s", red_addr)
        blue_sock, blue_addr = self._server_sock.accept()
        log.info("BLUE connected from %s", blue_addr)

        return TCPConnection(red_sock), TCPConnection(blue_sock)

    def shutdown(self) -> None:
        if self._server_sock is not None:
            self._server_sock.close()
            self._server_sock = None


def _setup_logging():
    import os, datetime
    os.makedirs("logs/server", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"logs/server/{ts}.log"
    handler = FileHandler(filename, mode="w")
    handler.setFormatter(Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(DEBUG)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    _setup_logging()
    server = TCPGameServer(port=port)
    try:
        result = server.run_game()
        log.info("Game over: %s", result)
        print(f"Game over: {result}")
    finally:
        server.shutdown()
