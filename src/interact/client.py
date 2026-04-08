"""
Client-side: GameClient contract, CLIGameClient, TCP transport.
"""

import json
import logging
import socket
from abc import abstractmethod

from core.type import Card, PlayerView
from interact.player import _recv, _send
from interact.serial import Deserializer

log = logging.getLogger("client")


# ── GameClient contract ───────────────────────────────────────

class GameClient:
  """Client-side contract. Frontends implement this."""

  @abstractmethod
  def on_state(self, view: PlayerView) -> None:
    """Render updated visible game state.
    Game result is part of PlayerView — detect game over here."""
    pass

  @abstractmethod
  def on_prompt(self, text: str, options: list[str]) -> int:
    """Display a prompt and return the chosen option index."""
    pass

  @abstractmethod
  def on_notify(self, text: str) -> None:
    """Display a notification message."""
    pass


# ── CLIGameClient ─────────────────────────────────────────────

def _card_names(cards: list[Card]) -> str:
    return ", ".join(c.display_name for c in cards)

class CLIGameClient(GameClient):
    """Terminal-based game client."""

    def on_state(self, view: PlayerView) -> None:
        log.debug("on_state: hp=%s hand=%d deck=%d",
                  view.hp, len(view.hand), view.deck_size)

        print("\n--- Game State ---")
        print(f"  HP: {view.hp}")

        if view.hand:
            print(f"  Hand: [{_card_names(view.hand)}]")

        if view.equipment:
            print(f"  Equipment: [{_card_names(view.equipment)}]")

        for i, (weapon, sharpness, kills) in enumerate(view.weapons):
            if weapon is not None:
                print(f"  Weapon {i}: {weapon.display_name} (sharpness {sharpness}, {kills} kills)")
            else:
                print(f"  Weapon {i}: Empty")

        print(f"  Deck: {view.deck_size}  Refresh: {view.refresh_size}  Discard: {view.discard_size}")

        if view.sidebar:
            print(f"  Sidebar: [{_card_names(view.sidebar)}]")

        for label, cards in [
            ("Top Distant", view.action_field_top_distant),
            ("Top Hidden", view.action_field_top_hidden),
            ("Bottom Hidden", view.action_field_bottom_hidden),
            ("Bottom Distant", view.action_field_bottom_distant),
        ]:
            if cards:
                print(f"  {label}: [{_card_names(cards)}]")

        print(f"  Opponent: {view.opp_equipment_count} equipment, "
              f"deck {view.opp_deck_size}, refresh {view.opp_refresh_size}, "
              f"discard {view.opp_discard_size}")

        for label, cards in [
            ("Opp Top Distant", view.opp_action_field_top_distant),
            ("Opp Bottom Distant", view.opp_action_field_bottom_distant),
        ]:
            if cards:
                print(f"  {label}: [{_card_names(cards)}]")

        hidden_top = view.opp_action_field_top_hidden_count
        hidden_bot = view.opp_action_field_bottom_hidden_count
        if hidden_top or hidden_bot:
            print(f"  Opp Hidden: top={hidden_top}, bottom={hidden_bot}")

        print(f"  Priority: {view.priority}")
        print(f"  Guard deck: {view.guard_deck_size}")

        if view.game_result is not None:
            r = view.game_result
            print(f"\n  *** GAME OVER: {r.outcome} ***")
            if r.winners:
                print(f"  Winners: {r.winners}")
        print("------------------")

    def on_prompt(self, text: str, options: list[str]) -> int:
        log.info("on_prompt: %r  options=%s", text, options)
        print(f"\n{text}")
        for i, opt in enumerate(options):
            print(f"  {i}: {opt}")
        while True:
            try:
                choice = int(input("  > "))
                if 0 <= choice < len(options):
                    log.info("on_prompt response: %d (%s)", choice, options[choice])
                    return choice
                print(f"  Choose 0-{len(options)-1}")
            except ValueError:
                print("  Enter a number")

    def on_notify(self, text: str) -> None:
        log.info("on_notify: %s", text)
        print(f"\n[!] {text}")


# ── TCP transport + main loop ─────────────────────────────────

def run_client(host: str, port: int, client: GameClient):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    log.info("Connected to %s:%d", host, port)
    print(f"Connected to {host}:{port}")

    deserializer: Deserializer | None = None

    try:
        while True:
            msg = _recv(sock)
            log.debug("recv: type=%s", msg["type"])

            match msg["type"]:
                case "catalog":
                    deserializer = Deserializer.from_catalog(msg["cards"])
                case "state":
                    assert deserializer is not None
                    client.on_state(deserializer.player_view(msg["view"]))
                case "prompt":
                    choice = client.on_prompt(msg["text"], msg["options"])
                    _send(sock, {"type": "response", "choice": choice})
                    log.debug("sent response: choice=%d", choice)
                case "notify":
                    client.on_notify(msg["text"])
                case "close":
                    log.info("Server closed the connection")
                    print("\nServer closed the connection.")
                    break
    except ConnectionError:
        log.warning("Disconnected from server")
        print("\nDisconnected from server.")
    finally:
        sock.close()


def _setup_logging():
    import os, datetime
    os.makedirs("logs/client", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pid = os.getpid()
    filename = f"logs/client/{ts}_{pid}.log"
    handler = logging.FileHandler(filename, mode="w")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)


if __name__ == "__main__":
    import sys
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
    _setup_logging()
    run_client(host, port, CLIGameClient())
