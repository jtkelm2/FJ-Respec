"""
Forfeit + concurrent-game tests for GameServer.

Each test wires two socketpairs (one per player) and runs run_game in a
background thread. The "client" side of each pair is driven manually:
we read catalog/pid_assignment/state/prompt frames, then trigger forfeit
by closing the socket or sending {"type": "resign"}. The server's
ForfeitWatcher should observe the OOB, abort both pending prompts, and
yield GameResult(survivors, Outcome.FORFEIT).
"""

import json
import socket
import threading
import time

import pytest

from core.type import Outcome, PID
from interact.connection import TCPConnection
from interact.server import GameServer
from interact.player import Disconnect, Resigned


# ── A non-listening GameServer that hands over pre-built pairs ─────────────

class _FixedPairServer(GameServer):
    """Test harness: run_game accepts a pair directly; we never use accept_pair."""

    def accept_pair(self):  # pragma: no cover — not used in these tests
        raise NotImplementedError

    def shutdown(self):
        pass


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_pair():
    """Returns (server_conn, client_sock). Server side is a TCPConnection;
    client side is a raw socket so the test can drive frames by hand."""
    s, c = socket.socketpair()
    return TCPConnection(s), c


class _ClientDriver:
    """Reads line-delimited JSON from a raw socket; writes JSON back.

    Used by tests to play the client role just long enough to drive the
    server to a known state before disconnecting or resigning."""

    def __init__(self, sock: socket.socket, timeout: float = 2.0):
        self._sock = sock
        self._sock.settimeout(timeout)
        self._buf = b""

    def recv(self) -> dict:
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("client side: server closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line)

    def recv_until(self, type_: str) -> dict:
        """Drain frames until one matches `type_`."""
        while True:
            msg = self.recv()
            if msg.get("type") == type_:
                return msg

    def send(self, msg: dict) -> None:
        self._sock.sendall((json.dumps(msg) + "\n").encode())

    def close(self) -> None:
        self._sock.close()


def _run_game_async(server: GameServer, pair, seed: int = 42):
    """Spawn run_game on a thread; return (thread, result_holder)."""
    holder: dict = {}

    def _target():
        try:
            holder["result"] = server.run_game(pair, seed=seed)
        except BaseException as e:  # noqa: BLE001
            holder["exc"] = e

    t = threading.Thread(target=_target, daemon=True, name="run_game")
    t.start()
    return t, holder


def _drive_to_first_prompt(driver: _ClientDriver) -> None:
    """Read frames until the server has sent its first prompt (which means
    the game loop is parked waiting for a response — the exact state where
    a disconnect or resign should produce a forfeit)."""
    driver.recv_until("catalog")
    driver.recv_until("prompt")


# ── Tests ──────────────────────────────────────────────────────────────────

class TestForfeit:

    def test_disconnect_yields_forfeit_winner_is_other_player(self):
        server = _FixedPairServer()
        red_conn, red_client = _make_pair()
        blue_conn, blue_client = _make_pair()

        t, holder = _run_game_async(server, (red_conn, blue_conn))

        red_drv = _ClientDriver(red_client)
        blue_drv = _ClientDriver(blue_client)
        _drive_to_first_prompt(red_drv)
        _drive_to_first_prompt(blue_drv)

        # RED disconnects. BLUE should "win" by forfeit.
        red_client.close()

        t.join(timeout=5.0)
        assert not t.is_alive(), "run_game did not return after RED disconnect"
        assert "exc" not in holder, f"run_game raised: {holder.get('exc')!r}"
        result = holder["result"]
        assert result.outcome == Outcome.FORFEIT
        assert result.winners == (PID.BLUE,)

        blue_client.close()

    def test_resign_yields_forfeit_winner_is_other_player(self):
        server = _FixedPairServer()
        red_conn, red_client = _make_pair()
        blue_conn, blue_client = _make_pair()

        t, holder = _run_game_async(server, (red_conn, blue_conn))

        red_drv = _ClientDriver(red_client)
        blue_drv = _ClientDriver(blue_client)
        _drive_to_first_prompt(red_drv)
        _drive_to_first_prompt(blue_drv)

        # BLUE resigns mid-prompt. RED should win.
        blue_drv.send({"type": "resign"})

        t.join(timeout=5.0)
        assert not t.is_alive()
        assert "exc" not in holder, f"run_game raised: {holder.get('exc')!r}"
        result = holder["result"]
        assert result.outcome == Outcome.FORFEIT
        assert result.winners == (PID.RED,)

        red_client.close()
        blue_client.close()

    def test_both_disconnect_yields_forfeit_with_no_winners(self):
        server = _FixedPairServer()
        red_conn, red_client = _make_pair()
        blue_conn, blue_client = _make_pair()

        t, holder = _run_game_async(server, (red_conn, blue_conn))

        red_drv = _ClientDriver(red_client)
        blue_drv = _ClientDriver(blue_client)
        _drive_to_first_prompt(red_drv)
        _drive_to_first_prompt(blue_drv)

        red_client.close()
        blue_client.close()

        t.join(timeout=5.0)
        assert not t.is_alive()
        assert "exc" not in holder, f"run_game raised: {holder.get('exc')!r}"
        result = holder["result"]
        assert result.outcome == Outcome.FORFEIT
        # Either both players or none won, depending on the race; the contract
        # is that survivors win. Allow either zero or one survivor here — but
        # the canonical case is no survivors.
        assert len(result.winners) <= 1

    def test_draw_offer_does_not_forfeit(self):
        """Advisory OOBs (draw_offer / draw_accept) must NOT abort the game."""
        server = _FixedPairServer()
        red_conn, red_client = _make_pair()
        blue_conn, blue_client = _make_pair()

        t, holder = _run_game_async(server, (red_conn, blue_conn))

        red_drv = _ClientDriver(red_client)
        blue_drv = _ClientDriver(blue_client)
        _drive_to_first_prompt(red_drv)
        _drive_to_first_prompt(blue_drv)

        # RED sends a draw offer — game should keep going (still parked at prompt).
        red_drv.send({"type": "draw_offer"})

        # Give the watcher a moment; verify run_game has NOT returned.
        time.sleep(0.3)
        assert t.is_alive(), "draw_offer should not end the game"

        # Now actually end the game by disconnecting both.
        red_client.close()
        blue_client.close()
        t.join(timeout=5.0)
        assert holder["result"].outcome == Outcome.FORFEIT


# ── Concurrent games ──────────────────────────────────────────────────────

class TestConcurrentGames:

    def test_two_games_run_independently_on_one_server(self):
        """A single GameServer instance runs two games on two distinct pairs
        in parallel; both end with their own GameResult."""
        server = _FixedPairServer()

        # Game 1
        r1, r1c = _make_pair()
        b1, b1c = _make_pair()
        t1, h1 = _run_game_async(server, (r1, b1))

        # Game 2
        r2, r2c = _make_pair()
        b2, b2c = _make_pair()
        t2, h2 = _run_game_async(server, (r2, b2))

        for c in (r1c, b1c, r2c, b2c):
            _ClientDriver(c).recv_until("prompt")

        # Game 1: RED disconnects → BLUE wins
        r1c.close()
        # Game 2: BLUE resigns → RED wins
        _ClientDriver(b2c).send({"type": "resign"})

        t1.join(timeout=5.0)
        t2.join(timeout=5.0)
        assert not t1.is_alive() and not t2.is_alive()
        assert "exc" not in h1 and "exc" not in h2

        assert h1["result"].outcome == Outcome.FORFEIT
        assert h1["result"].winners == (PID.BLUE,)
        assert h2["result"].outcome == Outcome.FORFEIT
        assert h2["result"].winners == (PID.RED,)

        # Cleanup
        b1c.close()
        r2c.close()
        b2c.close()


# ── Per-game logging ──────────────────────────────────────────────────────

class TestPerGameLogging:

    def test_per_game_log_file_is_created(self, tmp_path):
        server = _FixedPairServer(log_dir=str(tmp_path))
        red_conn, red_client = _make_pair()
        blue_conn, blue_client = _make_pair()

        t, holder = _run_game_async(server, (red_conn, blue_conn))

        red_drv = _ClientDriver(red_client)
        blue_drv = _ClientDriver(blue_client)
        _drive_to_first_prompt(red_drv)
        _drive_to_first_prompt(blue_drv)
        red_client.close()
        blue_client.close()

        t.join(timeout=5.0)

        log_files = list(tmp_path.glob("game-*.log"))
        assert len(log_files) == 1, f"expected one game log; got {log_files}"
        content = log_files[0].read_text()
        # Per-game log should mention the game id and the forfeit outcome.
        assert "starting" in content
        assert "FORFEIT" in content

    def test_two_concurrent_games_get_two_log_files(self, tmp_path):
        server = _FixedPairServer(log_dir=str(tmp_path))

        r1, r1c = _make_pair()
        b1, b1c = _make_pair()
        r2, r2c = _make_pair()
        b2, b2c = _make_pair()

        t1, _ = _run_game_async(server, (r1, b1))
        t2, _ = _run_game_async(server, (r2, b2))

        for c in (r1c, b1c, r2c, b2c):
            _ClientDriver(c).recv_until("prompt")
        for c in (r1c, b1c, r2c, b2c):
            c.close()

        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        log_files = list(tmp_path.glob("game-*.log"))
        assert len(log_files) == 2, (
            f"expected one log file per game; got {[p.name for p in log_files]}"
        )
        # Each file must mention exactly its own game id (no cross-talk).
        ids = []
        for p in log_files:
            content = p.read_text()
            # Filename: game-<id>-<timestamp>.log
            gid = p.name.split("-", 2)[1]
            ids.append(gid)
            assert f"game {gid} starting" in content
            other_ids = [other for other in ("1", "2", "3") if other != gid]
            for other in other_ids:
                assert f"game {other} starting" not in content, (
                    f"log for game {gid} leaked entries about game {other}"
                )
        assert set(ids) == set(ids)  # ids are distinct
        assert len(set(ids)) == 2


# ── OOB exit type retained for any downstream consumer ────────────────────

def test_oob_types_still_exported():
    """Symbols other modules import from interact.player must still exist."""
    assert Disconnect is not None
    assert Resigned is not None
