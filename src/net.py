"""
Server-side networking: TCPPlayer, TCPGameServer, AsyncAggregateInterpreter.

Wire protocol: newline-delimited JSON over TCP.
  Server → Client messages:
    {"type": "state",  "view": {...}}
    {"type": "prompt", "text": "...", "options": ["...", ...]}
    {"type": "notify", "text": "..."}
    {"type": "close"}
  Client → Server messages:
    {"type": "response", "choice": <int>}
"""

import json
import logging
import queue
import socket
import threading
from dataclasses import asdict
from enum import Enum

from core.type import (
    PID, GameState, GameResult, Outcome, CardType, CardView,
    PromptHalf, Prompt, PKind,
    Response, PlayerView, compute_player_view,
)
from core.interpret import Interpreter, Player, GameServer
from core.engine import run
from phase.game import game_loop
from phase.setup import create_initial_state

log = logging.getLogger("server")


# ── JSON wire helpers ─────────────────────────────────────────

class _GameEncoder(json.JSONEncoder):
    """Handles Enum and tuple serialization for the wire protocol."""
    def default(self, o):
        if isinstance(o, Enum):
            return o.name
        return super().default(o)

def _serialize_view(view: PlayerView) -> dict:
    return json.loads(json.dumps(asdict(view), cls=_GameEncoder))

def _deserialize_card_view(d: dict) -> CardView:
    return CardView(
        name=d["name"],
        display_name=d["display_name"],
        level=d["level"],
        types=tuple(CardType[t] for t in d["types"]),
    )

def deserialize_view(d: dict) -> PlayerView:
    """Reconstruct a PlayerView from a JSON-deserialized dict."""
    def _cards(lst): return [_deserialize_card_view(c) for c in lst]
    def _weapon(w): return (
        _deserialize_card_view(w[0]) if w[0] is not None else None,
        w[1], w[2],
    )
    gr = d["game_result"]
    game_result = None if gr is None else GameResult(
        winners=tuple(PID[w] for w in gr["winners"]),
        outcome=Outcome[gr["outcome"]],
    )
    return PlayerView(
        hp=d["hp"],
        hand=_cards(d["hand"]),
        equipment=_cards(d["equipment"]),
        weapons=[_weapon(w) for w in d["weapons"]],
        deck_size=d["deck_size"],
        refresh_size=d["refresh_size"],
        discard_size=d["discard_size"],
        action_field_top_distant=_cards(d["action_field_top_distant"]),
        action_field_top_hidden=_cards(d["action_field_top_hidden"]),
        action_field_bottom_hidden=_cards(d["action_field_bottom_hidden"]),
        action_field_bottom_distant=_cards(d["action_field_bottom_distant"]),
        sidebar=_cards(d["sidebar"]),
        opp_equipment_count=d["opp_equipment_count"],
        opp_weapons=[tuple(w) for w in d["opp_weapons"]],
        opp_deck_size=d["opp_deck_size"],
        opp_refresh_size=d["opp_refresh_size"],
        opp_discard_size=d["opp_discard_size"],
        opp_action_field_top_distant=_cards(d["opp_action_field_top_distant"]),
        opp_action_field_top_hidden_count=d["opp_action_field_top_hidden_count"],
        opp_action_field_bottom_hidden_count=d["opp_action_field_bottom_hidden_count"],
        opp_action_field_bottom_distant=_cards(d["opp_action_field_bottom_distant"]),
        priority=PID[d["priority"]],
        guard_deck_size=d["guard_deck_size"],
        game_result=game_result,
    )

def _send(sock: socket.socket, msg: dict) -> None:
    data = json.dumps(msg, cls=_GameEncoder) + "\n"
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

    def __init__(self, sock: socket.socket, label: str = "?"):
        self._sock = sock
        self._label = label

    def push_state(self, view: PlayerView) -> None:
        log.debug("[%s] push_state (hp=%d, hand=%d, deck=%d)",
                  self._label, view.hp, len(view.hand), view.deck_size)
        _send(self._sock, {"type": "state", "view": _serialize_view(view)})

    def request(self, prompt_half: PromptHalf) -> int:
        log.info("[%s] request: %r  options=%s",
                 self._label, prompt_half.text, prompt_half.options)
        _send(self._sock, {
            "type": "prompt",
            "text": prompt_half.text,
            "options": prompt_half.options,
        })
        msg = _recv(self._sock)
        choice = msg["choice"]
        log.info("[%s] response: %d (%s)",
                 self._label, choice, prompt_half.options[choice] if choice < len(prompt_half.options) else "?")
        return choice

    def notify(self, text: str) -> None:
        log.info("[%s] notify: %s", self._label, text)
        _send(self._sock, {"type": "notify", "text": text})

    def close(self) -> None:
        log.info("[%s] close", self._label)
        _send(self._sock, {"type": "close"})
        self._sock.close()


# ── AsyncAggregateInterpreter ────────────────────────────────

class AsyncAggregateInterpreter(Interpreter):
    """Composes two Players into an Interpreter.
    Pushes state diffs and handles AskBoth/AskEither concurrency.

    For EITHER prompts with multiple players (from simultaneously()),
    outstanding requests persist across interpret() calls. A player
    who lost a previous race keeps their blocking request() thread
    alive — no duplicate prompt is sent.
    """

    def __init__(self, g: GameState, red: Player, blue: Player):
        self._g = g
        self._players = {PID.RED: red, PID.BLUE: blue}
        self._last_view: dict[PID, PlayerView] = {}
        # Shared queue for EITHER race results: (PID, choice)
        self._either_results: queue.Queue[tuple[PID, int]] = queue.Queue()
        # PIDs that have an active request thread feeding _either_results
        self._outstanding: set[PID] = set()

    def push_if_changed(self, pid: PID) -> None:
        view = compute_player_view(self._g, pid)
        if pid not in self._last_view or view != self._last_view[pid]:
            log.debug("push_if_changed: %s view changed, pushing", pid.name)
            self._players[pid].push_state(view)
            self._last_view[pid] = view
        else:
            log.debug("push_if_changed: %s view unchanged, skipping", pid.name)

    def interpret(self, prompt: Prompt) -> Response:
        players_in_prompt = [pid.name for pid in prompt.for_player]
        log.info("interpret: kind=%s players=%s", prompt.kind.name, players_in_prompt)

        for pid in PID:
            self.push_if_changed(pid)

        match prompt.kind:
            case PKind.BOTH:
                log.info("interpret: BOTH — sending to %s concurrently", players_in_prompt)
                results: dict[PID, int] = {}
                errors: list[Exception] = []

                def _ask(pid: PID, half: PromptHalf):
                    try:
                        results[pid] = self._players[pid].request(half)
                    except Exception as e:
                        errors.append(e)

                threads = []
                for pid, half in prompt.for_player.items():
                    t = threading.Thread(target=_ask, args=(pid, half))
                    threads.append(t)
                    t.start()
                for t in threads:
                    t.join()
                if errors:
                    raise errors[0]
                log.info("interpret: BOTH results=%s", {p.name: v for p, v in results.items()})
                return results

            case PKind.EITHER:
                # Start request threads only for players without one outstanding
                for pid, half in prompt.for_player.items():
                    if pid not in self._outstanding:
                        self._outstanding.add(pid)
                        log.info("interpret: EITHER — starting request for %s: %r",
                                 pid.name, half.text)
                        def _req(p=pid, h=half):
                            choice = self._players[p].request(h)
                            self._either_results.put((p, choice))
                        threading.Thread(target=_req, daemon=True).start()
                    else:
                        log.info("interpret: EITHER — %s already has outstanding request, reusing",
                                 pid.name)

                # Wait for a result from any player in this prompt
                while True:
                    rpid, choice = self._either_results.get()
                    self._outstanding.discard(rpid)
                    if rpid in prompt.for_player:
                        log.info("interpret: EITHER answered by %s (choice=%d)", rpid.name, choice)
                        return {rpid: choice}
                    log.warning("interpret: EITHER — stale result from %s, discarding", rpid.name)


# ── TCPGameServer ─────────────────────────────────────────────

class TCPGameServer(GameServer):

    def __init__(self, host: str = "0.0.0.0", port: int = 9000):
        self._host = host
        self._port = port
        self._server_sock: socket.socket | None = None

    def await_players(self) -> tuple[Player, Player]:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(2)
        log.info("Listening on %s:%d ...", self._host, self._port)

        red_sock, red_addr = self._server_sock.accept()
        log.info("RED connected from %s", red_addr)
        blue_sock, blue_addr = self._server_sock.accept()
        log.info("BLUE connected from %s", blue_addr)

        return TCPPlayer(red_sock, "RED"), TCPPlayer(blue_sock, "BLUE")

    def run_game(self, seed: int | None = None) -> GameResult:
        red, blue = self.await_players()
        g = create_initial_state(seed=seed)

        red.notify(f"You are {g.players[PID.RED].role.name} (RED)")
        blue.notify(f"You are {g.players[PID.BLUE].role.name} (BLUE)")

        interp = AsyncAggregateInterpreter(g, red, blue)
        run(g, game_loop(), interp)

        # Push final state (includes game_result) then close
        for pid in PID:
            interp.push_if_changed(pid)
            interp._players[pid].close()

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
    handler = logging.FileHandler(filename, mode="w")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)


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
