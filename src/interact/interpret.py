import logging
import queue
import threading
from abc import abstractmethod
from dataclasses import dataclass

from core.type import (
    PID, GameState, Prompt, PKind, PromptHalf,
    Response, PlayerView, compute_player_view,
    Effect,
)
from interact.player import Player

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
  """Sequential aggregation of two players; not intended for async composition."""
  i1: Player
  i2: Player

  def _route(self, pid: PID) -> Player:
    return self.i1 if pid == PID.RED else self.i2

  def interpret(self, prompt: Prompt) -> Response:
    match prompt.kind:
      case PKind.BOTH: return {pid: self._route(pid).request(prompt_half) for pid, prompt_half in prompt.for_player.items()}
      case PKind.EITHER:
        pid, prompt_half = next(iter(prompt.for_player.items()))
        return {pid: self._route(pid).request(prompt_half)}


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
        self._either_results: queue.Queue[tuple[PID, int]] = queue.Queue()
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

                while True:
                    rpid, choice = self._either_results.get()
                    self._outstanding.discard(rpid)
                    if rpid in prompt.for_player:
                        log.info("interpret: EITHER answered by %s (choice=%d)", rpid.name, choice)
                        return {rpid: choice}
                    log.warning("interpret: EITHER — stale result from %s, discarding", rpid.name)
