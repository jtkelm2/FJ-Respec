"""
Server-side: GameServer contract, TCPGameServer.
"""

from abc import abstractmethod
from logging import DEBUG, FileHandler, Formatter, getLogger
from socket import AF_INET, SO_REUSEADDR, SOCK_STREAM, SOL_SOCKET, socket

from core.type import PID, GameResult
from interact.player import Player, RemotePlayer, TCPConnection
from interact.interpret import run, AsyncAggregateInterpreter, ViewPushingInterpreter
from interact.serial import Accumulator
from phase.game import game_loop
from phase.setup import create_initial_state

log = getLogger("server")


class GameServer:
  """Abstraction for hosting a game."""

  @abstractmethod
  def run_game(self, seed: int | None = None) -> GameResult:
    """Set up and run a complete game. Returns the result."""
    pass

  @abstractmethod
  def shutdown(self) -> None:
    """Release all resources."""
    pass


class TCPGameServer(GameServer):

    def __init__(self, host: str = "0.0.0.0", port: int = 9000):
        self._host = host
        self._port = port
        self._server_sock: socket | None = None

    def _await_sockets(self) -> tuple[socket, socket]:
        self._server_sock = socket(AF_INET, SOCK_STREAM)
        self._server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(2)
        log.info("Listening on %s:%d ...", self._host, self._port)

        red_sock, red_addr = self._server_sock.accept()
        log.info("RED connected from %s", red_addr)
        blue_sock, blue_addr = self._server_sock.accept()
        log.info("BLUE connected from %s", blue_addr)

        return red_sock, blue_sock

    def run_game(self, seed: int | None = None) -> GameResult:
        red_sock, blue_sock = self._await_sockets()
        g = create_initial_state(seed=seed)

        acc = Accumulator(g)
        serializer = acc.serializer()
        catalog_msg = {"type": "catalog", "cards": acc.catalog()}

        red_conn = TCPConnection(red_sock)
        blue_conn = TCPConnection(blue_sock)
        red_conn.send(catalog_msg)
        blue_conn.send(catalog_msg)

        red = RemotePlayer(red_conn, serializer, "RED")
        blue = RemotePlayer(blue_conn, serializer, "BLUE")

        red.notify(f"You are {g.players[PID.RED].role.name} (RED)")
        blue.notify(f"You are {g.players[PID.BLUE].role.name} (BLUE)")

        players: dict[PID, Player] = {PID.RED: red, PID.BLUE: blue}
        interp = ViewPushingInterpreter(g, players, AsyncAggregateInterpreter(red, blue))
        run(g, game_loop(), interp)

        # Push final state (includes game_result) then close
        for pid in PID:
            interp.push_if_changed(pid)
            players[pid].close()

        assert g.game_result is not None
        return g.game_result

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
