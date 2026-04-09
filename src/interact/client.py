"""
Client-side: GameClient contract, CLIGameClient, TCP transport.
"""

from abc import abstractmethod
from logging import DEBUG, FileHandler, Formatter, getLogger
from socket import AF_INET, SOCK_STREAM, socket

from interact.player import TCPConnection
from interact.serial import ClientOption, ClientPlayerView

log = getLogger("client")


# ── GameClient contract ───────────────────────────────────────

class GameClient:
  """Client-side contract. Frontends implement this."""

  @abstractmethod
  def on_catalog(self, catalog: list[dict]) -> None:
    """Receive the card catalog at session start."""
    pass

  @abstractmethod
  def on_state(self, view: ClientPlayerView) -> None:
    """Render updated visible game state."""
    pass

  @abstractmethod
  def on_prompt(self, text: str, options: list[ClientOption]) -> ClientOption:
    """Display a prompt and return the chosen option."""
    pass

  @abstractmethod
  def on_notify(self, text: str) -> None:
    """Display a notification message."""
    pass


# ── CLIGameClient ─────────────────────────────────────────────

class CLIGameClient(GameClient):
    """Terminal-based game client."""

    def __init__(self):
        self._cards: dict[int, dict] = {}

    def on_catalog(self, catalog: list[dict]) -> None:
        for entry in catalog:
            self._cards[entry["uid"]] = entry

    def _card_name(self, uid: int) -> str:
        entry = self._cards.get(uid)
        return entry["display_name"] if entry else f"uid:{uid}"  # pragma: no mutate

    def _card_names(self, uids: list[int]) -> str:
        return ", ".join(self._card_name(u) for u in uids)  # pragma: no mutate

    def _option_label(self, opt: ClientOption) -> str:
        match opt["type"]:
            case "text": return opt["text"]  # pragma: no mutate
            case "card": return self._card_name(opt["uid"])  # pragma: no mutate
            case "slot": return f"slot:{opt['uid']}"  # pragma: no mutate
            case "weapon_slot": return f"weapon:{opt['uid']}"  # pragma: no mutate
            case _: return str(opt)  # pragma: no mutate

    def on_state(self, view: ClientPlayerView) -> None:
        log.debug("on_state: hp=%s hand=%d deck=%d",
                  view["hp"], len(view["hand"]), view["deck_size"])

        print("\n--- Game State ---")  # pragma: no mutate
        print(f"  HP: {view['hp']}")  # pragma: no mutate

        if view["hand"]:
            print(f"  Hand: [{self._card_names(view['hand'])}]")  # pragma: no mutate

        if view["equipment"]:
            print(f"  Equipment: [{self._card_names(view['equipment'])}]")  # pragma: no mutate

        for i, (weapon_uid, sharpness, kills) in enumerate(view["weapons"]):
            if weapon_uid is not None:
                print(f"  Weapon {i}: {self._card_name(weapon_uid)} (sharpness {sharpness}, {kills} kills)")  # pragma: no mutate
            else:
                print(f"  Weapon {i}: Empty")  # pragma: no mutate

        print(f"  Deck: {view['deck_size']}  Refresh: {view['refresh_size']}  Discard: {view['discard_size']}")  # pragma: no mutate

        if view["sidebar"]:
            print(f"  Sidebar: [{self._card_names(view['sidebar'])}]")  # pragma: no mutate

        for label, key in [
            ("Top Distant", "action_field_top_distant"),
            ("Top Hidden", "action_field_top_hidden"),
            ("Bottom Hidden", "action_field_bottom_hidden"),
            ("Bottom Distant", "action_field_bottom_distant"),
        ]:
            if view[key]:
                print(f"  {label}: [{self._card_names(view[key])}]")  # pragma: no mutate

        print(f"  Opponent: {view['opp_equipment_count']} equipment, "  # pragma: no mutate
              f"deck {view['opp_deck_size']}, refresh {view['opp_refresh_size']}, "
              f"discard {view['opp_discard_size']}")

        for label, key in [
            ("Opp Top Distant", "opp_action_field_top_distant"),
            ("Opp Bottom Distant", "opp_action_field_bottom_distant"),
        ]:
            if view[key]:
                print(f"  {label}: [{self._card_names(view[key])}]")  # pragma: no mutate

        hidden_top = view["opp_action_field_top_hidden_count"]
        hidden_bot = view["opp_action_field_bottom_hidden_count"]
        if hidden_top or hidden_bot:
            print(f"  Opp Hidden: top={hidden_top}, bottom={hidden_bot}")  # pragma: no mutate

        print(f"  Priority: {view['priority']}")  # pragma: no mutate
        print(f"  Guard deck: {view['guard_deck_size']}")  # pragma: no mutate

        gr = view["game_result"]
        if gr is not None:
            print(f"\n  *** GAME OVER: {gr['outcome']} ***")  # pragma: no mutate
            if gr["winners"]:
                print(f"  Winners: {gr['winners']}")  # pragma: no mutate
        print("------------------")  # pragma: no mutate

    def on_prompt(self, text: str, options: list[ClientOption]) -> ClientOption:
        log.info("on_prompt: %r  options=%s", text, options)
        print(f"\n{text}")  # pragma: no mutate
        for i, opt in enumerate(options):
            print(f"  {i}: {self._option_label(opt)}")  # pragma: no mutate
        while True:
            try:
                choice = int(input("  > "))
                if 0 <= choice < len(options):
                    log.info("on_prompt response: %d", choice)
                    return options[choice]
                print(f"  Choose 0-{len(options)-1}")  # pragma: no mutate
            except ValueError:
                print("  Enter a number")  # pragma: no mutate

    def on_notify(self, text: str) -> None:
        log.info("on_notify: %s", text)
        print(f"\n[!] {text}")  # pragma: no mutate


# ── TCP transport + main loop ─────────────────────────────────

def run_client(host: str, port: int, client: GameClient):
    sock = socket(AF_INET, SOCK_STREAM)
    sock.connect((host, port))
    log.info("Connected to %s:%d", host, port)
    print(f"Connected to {host}:{port}")

    conn = TCPConnection(sock)

    try:
        while True:
            msg = conn.recv()
            log.debug("recv: type=%s", msg["type"])

            match msg["type"]:
                case "catalog":
                    client.on_catalog(msg["cards"])
                case "state":
                    client.on_state(msg["view"])
                case "prompt":
                    chosen = client.on_prompt(msg["text"], msg["options"])
                    conn.send({"type": "response", "option": chosen})
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
        conn.close()


def _setup_logging():
    import os, datetime
    os.makedirs("logs/client", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pid = os.getpid()
    filename = f"logs/client/{ts}_{pid}.log"
    handler = FileHandler(filename, mode="w")
    handler.setFormatter(Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(DEBUG)


if __name__ == "__main__":
    import sys
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
    _setup_logging()
    run_client(host, port, CLIGameClient())
