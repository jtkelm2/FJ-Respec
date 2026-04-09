"""
Tests for AsyncAggregateInterpreter's EITHER race handling.

Uses a QueuePlayer backed by a Connection that allows controlled timing
to verify no duplicate prompts are sent.
"""

import logging
import threading
import time
from queue import Queue

from core.type import PID, PromptHalf, PlayerView, Ask, TextOption, Option
from core.engine import simultaneously
from interact.player import RemotePlayer, Connection
from interact.serial import Accumulator
from interact.interpret import run, AsyncAggregateInterpreter
from phase.setup import create_initial_state

log = logging.getLogger("race_test")


class QueueConnection(Connection):
    """Connection where messages flow through queues for controlled timing."""
    def __init__(self, label: str):
        self.label = label
        self.outbox: Queue[dict] = Queue()
        self.inbox: Queue[dict] = Queue()

    def send(self, msg: dict) -> None:
        log.info("[%s] conn.send: %s", self.label, msg.get("type", "?"))
        self.outbox.put(msg)

    def recv(self) -> dict:
        msg = self.inbox.get()
        log.info("[%s] conn.recv: %s", self.label, msg.get("type", "?"))
        return msg

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
    acc = Accumulator(g)
    ser = acc.serializer()

    red_conn = QueueConnection("RED")
    blue_conn = QueueConnection("BLUE")
    red = RemotePlayer(red_conn, ser, "RED")
    blue = RemotePlayer(blue_conn, ser, "BLUE")
    interp = AsyncAggregateInterpreter(g, red, blue)

    def simple_effect(pid):
        def eff(g):
            response = yield Ask(pid, f"{pid.name}: Pick", [TextOption("A"), TextOption("B")])
            response = yield Ask(pid, f"{pid.name}: Pick again", [TextOption("X"), TextOption("Y")])
        return eff

    effect = simultaneously({pid: simple_effect(pid) for pid in PID})
    engine_thread = threading.Thread(target=run, args=(g, effect, interp), name="engine")
    engine_thread.start()

    # Wait for both players to receive prompts (drain state pushes + prompts)
    def _wait_for_prompt(conn: QueueConnection) -> None:
        while True:
            msg = conn.outbox.get(timeout=2)
            if msg["type"] == "prompt":
                return

    _wait_for_prompt(red_conn)
    _wait_for_prompt(blue_conn)

    # BLUE answers first
    blue_conn.inbox.put({"type": "response", "option": {"type": "text", "text": "A"}})
    time.sleep(0.1)

    # RED should NOT have received a duplicate prompt
    prompt_count = 0
    while not red_conn.outbox.empty():
        msg = red_conn.outbox.get_nowait()
        if msg["type"] == "prompt":
            prompt_count += 1
    assert prompt_count == 0, "RED received a duplicate prompt"

    # RED answers late
    red_conn.inbox.put({"type": "response", "option": {"type": "text", "text": "A"}})
    time.sleep(0.1)

    # Drain remaining prompts and answer them
    for _ in range(10):
        time.sleep(0.05)
        for conn in [red_conn, blue_conn]:
            while not conn.outbox.empty():
                msg = conn.outbox.get_nowait()
                if msg["type"] == "prompt":
                    conn.inbox.put({"type": "response", "option": {"type": "text", "text": "X"}})

    engine_thread.join(timeout=3)
    assert not engine_thread.is_alive()
