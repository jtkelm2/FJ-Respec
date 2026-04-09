import logging
from queue import Queue
from threading import Thread
from abc import abstractmethod
from dataclasses import dataclass

from core.type import (
    PID, GameState, Prompt, PKind, PromptHalf, Option,
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
  """Sequential aggregation of two players; for testing with ScriptedPlayer."""
  i1: Player
  i2: Player

  def _route(self, pid: PID) -> Player:
    return self.i1 if pid == PID.RED else self.i2

  def interpret(self, prompt: Prompt) -> Response:
    match prompt.kind:
      case PKind.BOTH:
        return {pid: self._route(pid).prompt(half) for pid, half in prompt.for_player.items()}
      case PKind.EITHER:
        pid, half = next(iter(prompt.for_player.items()))
        return {pid: self._route(pid).prompt(half)}


class AsyncAggregateInterpreter(Interpreter):
    """Composes two Players into an Interpreter via per-prompt worker threads.

    Each prompt sent to a player runs in a one-shot thread that blocks on
    player.prompt(half) and puts the result into a shared inbox. Outstanding
    prompts persist across interpret() calls — a player who lost an EITHER
    race keeps their thread alive, so no duplicate prompt is sent.
    """

    def __init__(self, g: GameState, red: Player, blue: Player):
        self._g = g
        self._players = {PID.RED: red, PID.BLUE: blue}
        self._last_view: dict[PID, PlayerView] = {}
        self._inbox: Queue[tuple[PID, Option]] = Queue()
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
                return self._interpret_both(prompt)
            case PKind.EITHER:
                return self._interpret_either(prompt)

    def _spawn_prompt(self, pid: PID, half: PromptHalf) -> None:
        """Spawn a worker thread that calls player.prompt(half) and puts the
        result in the inbox. Marks pid as outstanding."""
        self._outstanding.add(pid)
        log.info("interpret: spawning prompt for %s: %r", pid.name, half.text)
        def _worker(p=pid, h=half):
            try:
                option = self._players[p].prompt(h)
            except Exception as e:
                log.warning("_worker: %s prompt failed: %s", p.name, e)
                return
            self._inbox.put((p, option))
        Thread(target=_worker, daemon=True, name=f"prompt-{pid.name}").start()

    def _interpret_both(self, prompt: Prompt) -> Response:
        log.info("interpret: BOTH — sending to %s", [p.name for p in prompt.for_player])

        for pid, half in prompt.for_player.items():
            self._spawn_prompt(pid, half)

        results: dict[PID, Option] = {}
        needed = set(prompt.for_player.keys())

        while needed:
            rpid, option = self._inbox.get()
            self._outstanding.discard(rpid)
            if rpid in needed:
                results[rpid] = option
                needed.discard(rpid)
            else:
                log.warning("interpret: BOTH — stale option from %s", rpid.name)

        log.info("interpret: BOTH results=%s", {p.name: v for p, v in results.items()})
        return results

    def _interpret_either(self, prompt: Prompt) -> Response:
        for pid, half in prompt.for_player.items():
            if pid not in self._outstanding:
                self._spawn_prompt(pid, half)

        while True:
            rpid, option = self._inbox.get()
            self._outstanding.discard(rpid)
            if rpid in prompt.for_player:
                log.info("interpret: EITHER answered by %s (%s)", rpid.name, option)
                return {rpid: option}
            log.warning("interpret: EITHER — stale option from %s", rpid.name)
