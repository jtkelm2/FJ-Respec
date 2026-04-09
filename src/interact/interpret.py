import logging
from queue import Queue
import threading
from abc import abstractmethod
from dataclasses import dataclass

from core.type import (
    PID, GameState, Prompt, PKind, PromptHalf, Option,
    Response, PlayerView, compute_player_view,
    Effect,
)
from interact.player import Player, RemotePlayer

log = logging.getLogger("server")


class Interpreter:
  @abstractmethod
  def interpret(self, prompt: Prompt) -> Response:
    pass


def run(g: GameState, effect: Effect, i: Interpreter):
  e = effect(g)
  try:
    prompt = next(e)
    while True:
      response = i.interpret(prompt)
      prompt = e.send(response)
  except StopIteration:
    return


# ── Aggregate interpreters ────────────────────────────────────

@dataclass
class AggregateInterpreter(Interpreter):
  """Sequential aggregation of two players; for testing with ScriptedPlayer."""
  i1: Player
  i2: Player

  def _route(self, pid: PID) -> Player:
    return self.i1 if pid == PID.RED else self.i2

  def interpret(self, prompt: Prompt) -> Response:
    match prompt.kind:
      case PKind.BOTH:
        return {pid: self._route(pid).request(half) for pid, half in prompt.for_player.items()}
      case PKind.EITHER:
        pid, half = next(iter(prompt.for_player.items()))
        return {pid: self._route(pid).request(half)}


class AsyncAggregateInterpreter(Interpreter):
    """Composes two RemotePlayers into an Interpreter via Connection-level inbox.

    Each connection has a dedicated listener thread that calls conn.recv()
    in a loop, putting messages into a shared inbox. This naturally handles:
      - PKind.EITHER: return on first response; loser's thread stays alive.
      - PKind.BOTH: wait until all needed players respond.
      - OOB messages (resign, draw offers): handled inline.

    For EITHER prompts with multiple players (from simultaneously()),
    outstanding prompts persist across interpret() calls. A player who
    lost a previous race keeps their listener thread alive — no duplicate
    prompt is sent.
    """

    def __init__(self, g: GameState, red: RemotePlayer, blue: RemotePlayer):
        self._g = g
        self._players = {PID.RED: red, PID.BLUE: blue}
        self._conns = {PID.RED: red.conn, PID.BLUE: blue.conn}
        self._serializers = {pid: p._serializer for pid, p in self._players.items()}
        self._last_view: dict[PID, PlayerView] = {}
        self._inbox: Queue[tuple[PID, dict]] = Queue()
        self._outstanding: set[PID] = set()
        self._last_options: dict[PID, list[Option]] = {}

        # Start listener threads
        for pid in PID:
            t = threading.Thread(target=self._listener, args=(pid,), daemon=True)
            t.start()

    def _listener(self, pid: PID) -> None:
        """Dedicated recv loop for one connection."""
        conn = self._conns[pid]
        try:
            while True:
                msg = conn.recv()
                self._inbox.put((pid, msg))
        except (ConnectionError, OSError):
            log.info("_listener: %s disconnected", pid.name)

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
                return self._interpret_both(prompt)
            case PKind.EITHER:
                return self._interpret_either(prompt)

    def _send_prompt(self, pid: PID, half: PromptHalf) -> None:
        """Serialize and send a prompt via the connection, mark outstanding."""
        self._outstanding.add(pid)
        self._last_options[pid] = list(half.options)
        serialized_options = [self._serializers[pid].option(o) for o in half.options]
        self._conns[pid].send({
            "type": "prompt",
            "text": half.text,
            "options": serialized_options,
        })
        log.info("interpret: sent prompt to %s: %r", pid.name, half.text)

    def _resolve_response(self, pid: PID, msg: dict) -> Option:
        """Map a serialized response option back to an engine Option."""
        serialized = msg["option"]
        serializer = self._serializers[pid]
        for opt in self._last_options.get(pid, []):
            if serializer.option(opt) == serialized:
                return opt
        raise ValueError(f"Unknown option from {pid.name}: {serialized}")

    def _interpret_both(self, prompt: Prompt) -> Response:
        """Send prompts to all players, wait for all responses."""
        log.info("interpret: BOTH — sending to %s", [p.name for p in prompt.for_player])

        for pid, half in prompt.for_player.items():
            self._send_prompt(pid, half)

        results: dict[PID, Option] = {}
        needed = set(prompt.for_player.keys())

        while needed:
            rpid, msg = self._inbox.get()
            match msg.get("type"):
                case "response":
                    if rpid in needed:
                        results[rpid] = self._resolve_response(rpid, msg)
                        needed.discard(rpid)
                        self._outstanding.discard(rpid)
                    else:
                        log.warning("interpret: BOTH — stale response from %s", rpid.name)
                case "resign":
                    log.info("interpret: BOTH — %s resigned", rpid.name)
                case "draw":
                    log.info("interpret: BOTH — %s offers draw", rpid.name)

        log.info("interpret: BOTH results=%s", {p.name: v for p, v in results.items()})
        return results

    def _interpret_either(self, prompt: Prompt) -> Response:
        """Send prompts to non-outstanding players, return first response."""
        for pid, half in prompt.for_player.items():
            if pid not in self._outstanding:
                self._send_prompt(pid, half)

        while True:
            rpid, msg = self._inbox.get()
            match msg.get("type"):
                case "response":
                    self._outstanding.discard(rpid)
                    if rpid in prompt.for_player:
                        option = self._resolve_response(rpid, msg)
                        log.info("interpret: EITHER answered by %s (%s)", rpid.name, option)
                        return {rpid: option}
                    log.warning("interpret: EITHER — stale result from %s", rpid.name)
                case "resign":
                    log.info("interpret: EITHER — %s resigned", rpid.name)
                case "draw":
                    log.info("interpret: EITHER — %s offers draw", rpid.name)
