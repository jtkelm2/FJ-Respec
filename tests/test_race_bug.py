"""
Tests for AsyncAggregateInterpreter's EITHER race handling.

Uses a QueuePlayer that gates receive_option on a queue, allowing
controlled timing to verify no duplicate prompts are sent.
"""

import logging
import threading
import time
from queue import Queue

from core.type import PID, PromptHalf, PlayerView, Ask, TextOption, Option
from core.engine import simultaneously
from interact.player import Player, OOB
from interact.interpret import run, AsyncAggregateInterpreter, ViewPushingInterpreter
from phase.setup import create_initial_state

log = logging.getLogger("race_test")


class QueuePlayer(Player):
    """Player where prompts and answers flow through queues."""
    def __init__(self, label: str):
        self.label = label
        self.prompts_received: Queue[PromptHalf] = Queue()
        self.answers: Queue[Option] = Queue()
        self.states: list[PlayerView] = []
        self._never = threading.Event()

    def push_state(self, view: PlayerView) -> None:
        self.states.append(view)

    def prompt(self, prompt_half: PromptHalf) -> Option:
        log.info("[%s] prompt: %r", self.label, prompt_half.text)
        self.prompts_received.put(prompt_half)
        answer = self.answers.get()
        log.info("[%s] answer: %s", self.label, answer)
        return answer

    def receive_oob(self) -> OOB:
        self._never.wait()
        raise RuntimeError("unreachable")

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
    """When one player wins a race, the loser's outstanding prompt
    is reused on the next interpret() call — not duplicated."""
    _setup_log()

    g = create_initial_state(seed=42)
    red = QueuePlayer("RED")
    blue = QueuePlayer("BLUE")
    players: dict[PID, Player] = {PID.RED: red, PID.BLUE: blue}
    interp = ViewPushingInterpreter(g, players, AsyncAggregateInterpreter(red, blue))

    def simple_effect(pid):
        def eff(g):
            response = yield Ask(pid, f"{pid.name}: Pick", [TextOption("A"), TextOption("B")])
            response = yield Ask(pid, f"{pid.name}: Pick again", [TextOption("X"), TextOption("Y")])
        return eff

    effect = simultaneously({pid: simple_effect(pid) for pid in PID})
    engine_thread = threading.Thread(target=run, args=(g, effect, interp), name="engine")
    engine_thread.start()

    red.prompts_received.get(timeout=2)
    blue.prompts_received.get(timeout=2)

    blue.answers.put(TextOption("A"))
    time.sleep(0.1)

    assert red.prompts_received.empty(), "RED received a duplicate prompt"

    red.answers.put(TextOption("A"))
    time.sleep(0.1)

    for _ in range(10):
        time.sleep(0.05)
        for player in [red, blue]:
            while not player.prompts_received.empty():
                player.prompts_received.get_nowait()
                player.answers.put(TextOption("X"))

    engine_thread.join(timeout=3)
    assert not engine_thread.is_alive()
