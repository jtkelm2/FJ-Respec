"""
Tests for AsyncAggregateInterpreter's EITHER race handling.

Uses a QueuePlayer that blocks on request() until an answer is fed,
allowing controlled timing to verify no duplicate prompts are sent.
"""

import logging
import threading
import time
from queue import Queue

from core.type import PID, PromptHalf, PlayerView, Ask
from core.interpret import Player
from core.engine import run, simultaneously
from net import AsyncAggregateInterpreter
from phase.setup import create_initial_state

log = logging.getLogger("race_test")


class QueuePlayer(Player):
    """Player where prompts and responses flow through queues."""
    def __init__(self, label: str):
        self.label = label
        self.prompts_received: Queue[PromptHalf] = Queue()
        self.answers: Queue[int] = Queue()
        self.states: list[PlayerView] = []

    def push_state(self, view: PlayerView) -> None:
        self.states.append(view)

    def request(self, prompt_half: PromptHalf) -> int:
        log.info("[%s] request: %r", self.label, prompt_half.text)
        self.prompts_received.put(prompt_half)
        answer = self.answers.get()
        log.info("[%s] answering: %d", self.label, answer)
        return answer

    def notify(self, text: str) -> None:
        pass

    def close(self) -> None:
        pass


def _setup_log():
    if not log.handlers:
        import os, datetime
        os.makedirs("logs/server", exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        handler = logging.FileHandler(f"logs/server/race_test_{ts}.log", mode="w")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(threadName)-12s %(levelname)-5s %(message)s",
            datefmt="%H:%M:%S"
        ))
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        server_log = logging.getLogger("server")
        server_log.addHandler(handler)
        server_log.setLevel(logging.DEBUG)


def test_no_duplicate_prompts_in_either_race():
    """When one player wins a race, the loser's outstanding request
    is reused on the next interpret() call — not duplicated."""
    _setup_log()

    g = create_initial_state(seed=42)
    red = QueuePlayer("RED")
    blue = QueuePlayer("BLUE")
    interp = AsyncAggregateInterpreter(g, red, blue)

    def simple_effect(pid):
        def eff(g):
            response = yield Ask(pid, f"{pid.name}: Pick", ["A", "B"])
            response = yield Ask(pid, f"{pid.name}: Pick again", ["X", "Y"])
        return eff

    effect = simultaneously({pid: simple_effect(pid) for pid in PID})
    engine_thread = threading.Thread(target=run, args=(g, effect, interp), name="engine")
    engine_thread.start()

    # Both players receive first prompt
    red.prompts_received.get(timeout=2)
    blue.prompts_received.get(timeout=2)

    # BLUE answers first — wins the race
    blue.answers.put(0)
    time.sleep(0.1)

    # RED should NOT have received a second prompt (the bug was a duplicate here)
    assert red.prompts_received.empty(), "RED received a duplicate prompt"

    # Now answer RED's original (still-outstanding) prompt
    red.answers.put(0)
    time.sleep(0.1)

    # Drain remaining prompts
    for _ in range(10):
        time.sleep(0.05)
        for player in [red, blue]:
            while not player.prompts_received.empty():
                player.prompts_received.get_nowait()
                player.answers.put(0)

    engine_thread.join(timeout=3)
    assert not engine_thread.is_alive()
