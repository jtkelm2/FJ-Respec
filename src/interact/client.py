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
  def on_catalog(self, cards: dict[str, dict],
                 slots: dict[str, dict[str, str]],
                 weapon_slots: dict[str, dict[str, str]]) -> None:
    """Receive the catalog at session start."""
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
        self._cards: dict[str, dict] = {}           # name → card entry
        # role → slot name, per owner
        self._my_slots: dict[str, str] = {}
        self._opp_slots: dict[str, str] = {}
        self._shared_slots: dict[str, str] = {}

    def on_catalog(self, cards: dict[str, dict],
                   slots: dict[str, dict[str, str]],
                   weapon_slots: dict[str, dict[str, str]]) -> None:
        self._cards = dict(cards)
        self._my_slots = dict(slots.get("self", {}))
        self._opp_slots = dict(slots.get("opponent", {}))
        self._shared_slots = dict(slots.get("shared", {}))

    def _card_display(self, name: str) -> str:
        entry = self._cards.get(name)
        return entry["display_name"] if entry else name  # pragma: no mutate

    def _card_displays(self, names: list[str]) -> str:
        return ", ".join(self._card_display(n) for n in names)  # pragma: no mutate

    def _my(self, view: ClientPlayerView, role: str) -> list[str] | int | None:
        """Get own slot contents by role."""
        name = self._my_slots.get(role)
        return view["slots"].get(name) if name else None

    def _opp(self, view: ClientPlayerView, role: str) -> list[str] | int | None:
        """Get opponent slot contents by role."""
        name = self._opp_slots.get(role)
        return view["slots"].get(name) if name else None

    def _shared(self, view: ClientPlayerView, role: str) -> list[str] | int | None:
        """Get shared slot contents by role."""
        name = self._shared_slots.get(role)
        return view["slots"].get(name) if name else None

    def _option_label(self, opt: ClientOption) -> str:
        match opt["type"]:
            case "text": return opt["text"]  # pragma: no mutate
            case "card":  # pragma: no mutate
                return f"card at {opt['slot']}[{opt['index']}]"  # pragma: no mutate
            case "slot":  # pragma: no mutate
                return opt["name"]  # pragma: no mutate
            case "weapon_slot":  # pragma: no mutate
                return opt["name"]  # pragma: no mutate
            case _: return str(opt)  # pragma: no mutate

    def on_state(self, view: ClientPlayerView) -> None:
        log.debug("on_state: hp=%s", view["hp"])

        print("\n--- Game State ---")  # pragma: no mutate
        print(f"  HP: {view['hp']}")  # pragma: no mutate

        hand = self._my(view, "hand")
        if hand and isinstance(hand, list):
            print(f"  Hand: [{self._card_displays(hand)}]")  # pragma: no mutate

        equip = self._my(view, "equipment")
        if equip and isinstance(equip, list):
            print(f"  Equipment: [{self._card_displays(equip)}]")  # pragma: no mutate

        for w in view["weapons"]:
            if w["card"] is not None:
                print(f"  Weapon: {self._card_display(w['card'])} "  # pragma: no mutate
                      f"(sharpness {w['sharpness']}, {w['kills']} kills)")
            else:
                print(f"  Weapon: Empty")  # pragma: no mutate

        deck = self._my(view, "deck")
        refresh = self._my(view, "refresh")
        discard = self._my(view, "discard")
        print(f"  Deck: {deck}  Refresh: {refresh}  Discard: {discard}")  # pragma: no mutate

        sidebar = self._my(view, "sidebar")
        if sidebar and isinstance(sidebar, list):
            print(f"  Sidebar: [{self._card_displays(sidebar)}]")  # pragma: no mutate

        for label, role in [
            ("Top Distant", "action_field_top_distant"),
            ("Top Hidden", "action_field_top_hidden"),
            ("Bottom Hidden", "action_field_bottom_hidden"),
            ("Bottom Distant", "action_field_bottom_distant"),
        ]:
            contents = self._my(view, role)
            if contents and isinstance(contents, list):
                print(f"  {label}: [{self._card_displays(contents)}]")  # pragma: no mutate

        opp_equip = self._opp(view, "equipment")
        opp_deck = self._opp(view, "deck")
        opp_refresh = self._opp(view, "refresh")
        opp_discard = self._opp(view, "discard")
        print(f"  Opponent: {opp_equip} equipment, "  # pragma: no mutate
              f"deck {opp_deck}, refresh {opp_refresh}, "
              f"discard {opp_discard}")

        for label, role in [
            ("Opp Top Distant", "action_field_top_distant"),
            ("Opp Bottom Distant", "action_field_bottom_distant"),
        ]:
            contents = self._opp(view, role)
            if contents and isinstance(contents, list):
                print(f"  {label}: [{self._card_displays(contents)}]")  # pragma: no mutate

        hidden_top = self._opp(view, "action_field_top_hidden")
        hidden_bot = self._opp(view, "action_field_bottom_hidden")
        if hidden_top or hidden_bot:
            print(f"  Opp Hidden: top={hidden_top}, bottom={hidden_bot}")  # pragma: no mutate

        print(f"  Priority: {view['priority']}")  # pragma: no mutate
        print(f"  Guard deck: {self._shared(view, 'guard_deck')}")  # pragma: no mutate

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
                    client.on_catalog(msg["cards"], msg["slots"],
                                      msg["weapon_slots"])
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
