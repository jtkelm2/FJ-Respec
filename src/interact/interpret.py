import logging
from queue import Queue
from threading import Thread
from abc import abstractmethod
from dataclasses import dataclass

from core.type import (
    PID, GameState, Prompt, PKind, PromptHalf, Option,
    Response, PlayerView, compute_player_view,
    Effect, Event,
)
from interact.player import Player, PlayerExited

_default_log = logging.getLogger("server")


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


class ViewPushingInterpreter(Interpreter):
    """Wraps an inner Interpreter and pushes per-player view diffs.

    Before each interpret() call, pushes the current PlayerView to any
    player whose view has changed since the last push. This responsibility
    is split out from AsyncAggregateInterpreter so the latter can focus
    on prompt routing alone."""

    def __init__(self, g: GameState, players: dict[PID, Player], inner: Interpreter,
                 logger: logging.Logger | None = None):
        self._g = g
        self._players = players
        self._inner = inner
        self._log = logger or _default_log
        self._last_view: dict[PID, PlayerView] = {}
        for pid in PID:
           self.push_if_changed(pid, None)

    def push_if_changed(self, pid: PID, events: list[Event] | None = None) -> None:
        view = compute_player_view(self._g, pid)
        if self._last_view.get(pid) != view:
            self._log.debug("ViewPushingInterpreter: %s view changed, pushing", pid.name)
            self._players[pid].push_state(view, events or [])
            self._last_view[pid] = view
        else:
            self._log.debug("ViewPushingInterpreter: %s view unchanged, skipping", pid.name)

    def interpret(self, prompt: Prompt) -> Response:
        events = self._g.drain_events()
        for pid in PID:
            self.push_if_changed(pid, events)
        return self._inner.interpret(prompt)


class AsyncAggregateInterpreter(Interpreter):
    """Composes two Players into an Interpreter via per-prompt worker threads.

    Each prompt sent to a player runs in a one-shot thread that blocks on
    player.prompt(half) and puts the result into a shared inbox. Outstanding
    prompts persist across interpret() calls — a player who lost an EITHER
    race keeps their thread alive, so no duplicate prompt is sent.

    If any prompt raises PlayerExited (the player resigned or was terminated
    by a forfeit watcher), the exception is propagated to the next interpret()
    caller so the game loop can unwind and the server can record a forfeit.
    """

    def __init__(self, red: Player, blue: Player, logger: logging.Logger | None = None):
        self._players = {PID.RED: red, PID.BLUE: blue}
        self._inbox: Queue[tuple[PID, Option | list[Option] | PlayerExited]] = Queue()
        self._outstanding: set[PID] = set()
        self._exited: PlayerExited | None = None
        self._log = logger or _default_log

    def interpret(self, prompt: Prompt) -> Response:
        if self._exited is not None:
            raise self._exited
        players_in_prompt = [pid.name for pid in prompt.for_player]
        self._log.info("interpret: kind=%s players=%s", prompt.kind.name, players_in_prompt)

        match prompt.kind:
            case PKind.BOTH:
                return self._interpret_both(prompt)
            case PKind.EITHER:
                return self._interpret_either(prompt)

    def _spawn_prompt(self, pid: PID, half: PromptHalf) -> None:
        """Spawn a worker thread that calls player.prompt(half) and puts the
        result (or a PlayerExited marker) in the inbox. Marks pid as outstanding."""
        self._outstanding.add(pid)
        self._log.info("interpret: spawning prompt for %s: %r", pid.name, half.text)
        def _worker(p=pid, h=half):
            try:
                option = self._players[p].prompt(h)
                self._inbox.put((p, option))
            except PlayerExited as e:
                self._log.info("_worker: %s prompt aborted (PlayerExited)", p.name)
                self._inbox.put((p, e))
            except Exception as e:
                self._log.warning("_worker: %s prompt failed: %s", p.name, e)
        Thread(target=_worker, daemon=True, name=f"prompt-{pid.name}").start()

    def _consume(self) -> tuple[PID, Option | list[Option]]:
        """Take one item from the inbox. If it's a PlayerExited marker, record
        it for future interpret() calls and re-raise immediately."""
        rpid, item = self._inbox.get()
        self._outstanding.discard(rpid)
        if isinstance(item, PlayerExited):
            self._exited = item
            raise item
        return rpid, item

    def _interpret_both(self, prompt: Prompt) -> Response:
        self._log.info("interpret: BOTH — sending to %s", [p.name for p in prompt.for_player])

        for pid, half in prompt.for_player.items():
            if pid not in self._outstanding:
                self._spawn_prompt(pid, half)

        results: dict[PID, Option | list[Option]] = {}
        needed = set(prompt.for_player.keys())

        while needed:
            rpid, option = self._consume()
            if rpid in needed:
                results[rpid] = option
                needed.discard(rpid)
            else:
                self._log.warning("interpret: BOTH — stale option from %s", rpid.name)

        self._log.info("interpret: BOTH results=%s", {p.name: v for p, v in results.items()})
        return results

    def _interpret_either(self, prompt: Prompt) -> Response:
        for pid, half in prompt.for_player.items():
            if pid not in self._outstanding:
                self._spawn_prompt(pid, half)

        while True:
            rpid, option = self._consume()
            if rpid in prompt.for_player:
                self._log.info("interpret: EITHER answered by %s (%s)", rpid.name, option)
                return {rpid: option}
            self._log.warning("interpret: EITHER — stale option from %s", rpid.name)
