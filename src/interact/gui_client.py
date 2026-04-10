"""
Tkinter-based GameClient.

Non-blocking with respect to user input: the recv loop runs on a daemon
thread and never waits on the user, so state updates from the server are
displayed even while a prompt is pending (e.g. while the partner is
answering an EITHER prompt). Each prompt is handled on its own short-lived
worker thread, which lets on_prompt() block on a per-call Event without
ever stalling the recv loop.
"""

import sys
import tkinter as tk
from logging import DEBUG, FileHandler, Formatter, getLogger
from socket import AF_INET, SOCK_STREAM, socket
from threading import Event, Lock, Thread

from interact.client import GameClient
from interact.player import TCPConnection
from interact.serial import ClientOption, ClientPlayerView

log = getLogger("client")


# ── Color scheme ──────────────────────────────────────────────

TYPE_COLORS = {
    "WEAPON":    "#d35400",
    "EQUIPMENT": "#2874a6",
    "ENEMY":     "#7b1f3f",
    "FOOD":      "#1e8449",
    "EVENT":     "#b7950b",
}
UNKNOWN_COLOR = "#444444"
HIDDEN_COLOR  = "#222222"
EMPTY_COLOR   = "#333333"
BG_COLOR      = "#1e1e1e"
PANEL_BG      = "#2a2a2a"
TEXT_COLOR    = "#eeeeee"
DIM_COLOR     = "#999999"
SEP_COLOR     = "#555555"

CARD_W = 70
CARD_H = 96


# ── Tooltip ───────────────────────────────────────────────────

class Tooltip:
    """Single shared tooltip; shown on <Enter>, hidden on <Leave>."""

    def __init__(self, root: tk.Tk):
        self._root = root
        self._tip: tk.Toplevel | None = None

    def show(self, widget: tk.Widget, text: str) -> None:
        self.hide()
        if not text:
            return
        x = widget.winfo_rootx() + widget.winfo_width() + 6
        y = widget.winfo_rooty()
        tip = tk.Toplevel(self._root)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip, text=text, bg="#fffbe0", fg="#000",
            justify="left", relief="solid", borderwidth=1,
            wraplength=320, font=("TkDefaultFont", 9), padx=6, pady=4,
        ).pack()
        self._tip = tip

    def hide(self) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


# ── GUI client ────────────────────────────────────────────────

class GUIGameClient(GameClient):
    """Tkinter game client. Recv loop runs on a daemon thread; UI updates
    are marshaled to the main thread via root.after()."""

    def __init__(self):
        self._cards: dict[int, dict] = {}
        self._send_lock = Lock()
        self._conn: TCPConnection | None = None

        self.root = tk.Tk()
        self.root.title("Fool's Journey")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("1280x820")
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._tooltip = Tooltip(self.root)
        self._build_widgets()

    # ── widgets ────────────────────────────────────────────────

    def _build_widgets(self) -> None:
        self._board = tk.Frame(self.root, bg=BG_COLOR)
        self._board.pack(side="left", fill="both", expand=True)

        self._side = tk.Frame(self.root, bg=PANEL_BG, width=320)
        self._side.pack(side="right", fill="y")
        self._side.pack_propagate(False)

        # Opponent zones (top)
        self._opp_summary       = self._make_text_row("Opponent")
        self._opp_equipment_row = self._make_card_row("Opp Equipment")
        self._opp_weapons_row   = self._make_card_row("Opp Weapons")
        self._opp_top_distant   = self._make_card_row("Opp Top Distant")
        self._opp_top_hidden    = self._make_card_row("Opp Top Hidden")
        self._opp_bottom_hidden = self._make_card_row("Opp Bottom Hidden")
        self._opp_bottom_distant= self._make_card_row("Opp Bottom Distant")

        tk.Frame(self._board, bg=SEP_COLOR, height=2).pack(fill="x", pady=8)

        # Your action field (middle)
        self._my_top_distant    = self._make_card_row("Top Distant")
        self._my_top_hidden     = self._make_card_row("Top Hidden")
        self._my_bottom_hidden  = self._make_card_row("Bottom Hidden")
        self._my_bottom_distant = self._make_card_row("Bottom Distant")

        tk.Frame(self._board, bg=SEP_COLOR, height=2).pack(fill="x", pady=8)

        # Your zones (bottom)
        self._my_equipment_row = self._make_card_row("Equipment")
        self._my_weapons_row   = self._make_card_row("Weapons")
        self._my_sidebar_row   = self._make_card_row("Sidebar")
        self._my_hand_row      = self._make_card_row("Hand")
        self._my_summary       = self._make_text_row("You")

        # Side panel: prompt + notifications
        self._prompt_title = tk.Label(
            self._side, text="(no prompt)", bg=PANEL_BG, fg=TEXT_COLOR,
            font=("TkDefaultFont", 11, "bold"),
            wraplength=300, justify="left", anchor="w",
        )
        self._prompt_title.pack(fill="x", padx=8, pady=(8, 4))

        self._prompt_buttons = tk.Frame(self._side, bg=PANEL_BG)
        self._prompt_buttons.pack(fill="x", padx=8)

        tk.Label(
            self._side, text="Messages", bg=PANEL_BG, fg=DIM_COLOR,
            font=("TkDefaultFont", 9, "italic"), anchor="w",
        ).pack(fill="x", padx=8, pady=(20, 0))

        self._notify_text = tk.Text(
            self._side, height=12, bg="#1a1a1a", fg=TEXT_COLOR,
            wrap="word", relief="flat", state="disabled",
            font=("TkDefaultFont", 9),
        )
        self._notify_text.pack(fill="both", expand=True, padx=8, pady=4)

    def _make_text_row(self, label: str) -> tk.Label:
        frame = tk.Frame(self._board, bg=BG_COLOR)
        frame.pack(fill="x", padx=8, pady=2)
        tk.Label(frame, text=label + ":", bg=BG_COLOR, fg=DIM_COLOR,
                 width=20, anchor="w", font=("TkDefaultFont", 9)).pack(side="left")
        value = tk.Label(frame, text="", bg=BG_COLOR, fg=TEXT_COLOR,
                         anchor="w", font=("TkFixedFont", 9))
        value.pack(side="left")
        return value

    def _make_card_row(self, label: str) -> tk.Frame:
        frame = tk.Frame(self._board, bg=BG_COLOR)
        frame.pack(fill="x", padx=8, pady=2)
        tk.Label(frame, text=label, bg=BG_COLOR, fg=DIM_COLOR,
                 width=20, anchor="w", font=("TkDefaultFont", 9)).pack(side="left")
        cards = tk.Frame(frame, bg=BG_COLOR, height=CARD_H)
        cards.pack(side="left", fill="x", expand=True)
        return cards

    # ── card rendering ─────────────────────────────────────────

    def _card_color(self, entry: dict) -> str:
        for t in entry.get("types", []):
            if t in TYPE_COLORS:
                return TYPE_COLORS[t]
        return UNKNOWN_COLOR

    def _clear(self, container: tk.Frame) -> None:
        for w in container.winfo_children():
            w.destroy()

    def _render_cards(self, container: tk.Frame, uids: list[int]) -> None:
        self._clear(container)
        for uid in uids:
            entry = self._cards.get(uid) or {
                "display_name": f"uid:{uid}", "text": "",
                "types": [], "level": None, "is_elusive": False,
            }
            self._make_card_widget(container, entry)

    def _render_hidden(self, container: tk.Frame, count: int) -> None:
        self._clear(container)
        for _ in range(count):
            self._make_hidden_widget(container)

    def _bind_tooltip(self, frame: tk.Widget, text: str) -> None:
        def enter(_e):
            self._tooltip.show(frame, text)
        def leave(_e):
            self._tooltip.hide()
        for child in (frame,) + tuple(frame.winfo_children()):
            child.bind("<Enter>", enter)
            child.bind("<Leave>", leave)

    def _make_card_widget(self, parent: tk.Frame, entry: dict) -> tk.Frame:
        bg = self._card_color(entry)
        bd = 3 if entry.get("is_elusive") else 1
        frame = tk.Frame(parent, bg=bg, width=CARD_W, height=CARD_H,
                         bd=bd, relief="solid")
        frame.pack(side="left", padx=2)
        frame.pack_propagate(False)

        tk.Label(
            frame, text=entry.get("display_name", "?"),
            bg=bg, fg="#ffffff",
            wraplength=CARD_W - 8,
            font=("TkDefaultFont", 8, "bold"),
            justify="center",
        ).place(relx=0.5, rely=0.5, anchor="center")

        level = entry.get("level")
        if level is not None:
            tk.Label(
                frame, text=str(level), bg="#000000", fg="#ffffff",
                font=("TkDefaultFont", 8, "bold"), padx=3,
            ).place(relx=0, rely=0, anchor="nw")

        tip = entry.get("text") or entry.get("display_name", "")
        self._bind_tooltip(frame, tip)
        return frame

    def _make_hidden_widget(self, parent: tk.Frame) -> None:
        frame = tk.Frame(parent, bg=HIDDEN_COLOR, width=CARD_W, height=CARD_H,
                         bd=1, relief="solid")
        frame.pack(side="left", padx=2)
        frame.pack_propagate(False)
        tk.Label(frame, text="?", bg=HIDDEN_COLOR, fg="#666666",
                 font=("TkDefaultFont", 24, "bold")).place(
            relx=0.5, rely=0.5, anchor="center")

    def _make_empty_weapon_widget(self, parent: tk.Frame) -> None:
        frame = tk.Frame(parent, bg=EMPTY_COLOR, width=CARD_W, height=CARD_H,
                         bd=1, relief="solid")
        frame.pack(side="left", padx=2)
        frame.pack_propagate(False)
        tk.Label(frame, text="(empty)", bg=EMPTY_COLOR, fg=DIM_COLOR,
                 font=("TkDefaultFont", 8)).place(
            relx=0.5, rely=0.5, anchor="center")

    def _make_opp_weapon_widget(self, parent: tk.Frame,
                                 sharpness: int, kills: int) -> None:
        bg = TYPE_COLORS["WEAPON"]
        frame = tk.Frame(parent, bg=bg, width=CARD_W, height=CARD_H,
                         bd=1, relief="solid")
        frame.pack(side="left", padx=2)
        frame.pack_propagate(False)
        tk.Label(frame, text=f"sh {sharpness}\n{kills} kills",
                 bg=bg, fg="#ffffff",
                 font=("TkDefaultFont", 8, "bold"),
                 justify="center").place(
            relx=0.5, rely=0.5, anchor="center")
        self._bind_tooltip(frame,
                           f"Opponent weapon\nsharpness {sharpness}\n{kills} kills")

    # ── GameClient interface ───────────────────────────────────

    def on_catalog(self, catalog: list[dict]) -> None:
        for entry in catalog:
            self._cards[entry["uid"]] = entry
        log.info("on_catalog: %d cards", len(catalog))

    def on_state(self, view: ClientPlayerView) -> None:
        log.debug("on_state: hp=%s hand=%d deck=%d",
                  view["hp"], len(view["hand"]), view["deck_size"])
        self.root.after(0, self._render_state, view)

    def _render_state(self, view: ClientPlayerView) -> None:
        self._opp_summary.config(text=(
            f"deck {view['opp_deck_size']:>2}  "
            f"refresh {view['opp_refresh_size']:>2}  "
            f"discard {view['opp_discard_size']:>2}  "
            f"equipment {view['opp_equipment_count']:>2}  "
            f"priority {view['priority']}  "
            f"guard-deck {view['guard_deck_size']}"
        ))

        # Opponent equipment is count-only — render as face-down placeholders.
        self._render_hidden(self._opp_equipment_row, view["opp_equipment_count"])

        self._clear(self._opp_weapons_row)
        for sharpness, kills in view["opp_weapons"]:
            self._make_opp_weapon_widget(self._opp_weapons_row, sharpness, kills)

        self._render_cards(self._opp_top_distant,    view["opp_action_field_top_distant"])
        self._render_hidden(self._opp_top_hidden,    view["opp_action_field_top_hidden_count"])
        self._render_hidden(self._opp_bottom_hidden, view["opp_action_field_bottom_hidden_count"])
        self._render_cards(self._opp_bottom_distant, view["opp_action_field_bottom_distant"])

        self._render_cards(self._my_top_distant,    view["action_field_top_distant"])
        self._render_cards(self._my_top_hidden,     view["action_field_top_hidden"])
        self._render_cards(self._my_bottom_hidden,  view["action_field_bottom_hidden"])
        self._render_cards(self._my_bottom_distant, view["action_field_bottom_distant"])

        self._render_cards(self._my_equipment_row, view["equipment"])

        self._clear(self._my_weapons_row)
        for uid, sharpness, kills in view["weapons"]:
            if uid is None:
                self._make_empty_weapon_widget(self._my_weapons_row)
            else:
                base = self._cards.get(uid, {})
                # Inject sharpness/kills into the tooltip without mutating the catalog.
                entry = dict(base)
                entry["text"] = (
                    f"sharpness {sharpness}, {kills} kills\n\n"
                    + (base.get("text") or "")
                )
                self._make_card_widget(self._my_weapons_row, entry)

        self._render_cards(self._my_sidebar_row, view["sidebar"])
        self._render_cards(self._my_hand_row,    view["hand"])

        self._my_summary.config(text=(
            f"HP {view['hp']:>2}  "
            f"deck {view['deck_size']:>2}  "
            f"refresh {view['refresh_size']:>2}  "
            f"discard {view['discard_size']:>2}  "
            f"hand {len(view['hand']):>2}"
        ))

        gr = view["game_result"]
        if gr is not None:
            self._show_notify(
                f"*** GAME OVER: {gr['outcome']} *** winners: {gr['winners']}"
            )

    def on_prompt(self, text: str, options: list[ClientOption]) -> ClientOption:
        # Called from a per-prompt worker thread spawned by _recv_loop.
        # We render the prompt on the tk thread, then block on a per-call
        # Event. If a *new* prompt arrives before the user clicks, the new
        # render replaces the buttons; this worker is then orphaned (its
        # Event will never fire) and stays parked until the connection
        # closes. Acceptable for barebones — only one outstanding worker
        # is ever wired up to live buttons.
        log.info("on_prompt: %r  options=%s", text, options)
        done = Event()
        holder: list[ClientOption] = []

        def callback(opt: ClientOption) -> None:
            holder.append(opt)
            done.set()

        self.root.after(0, self._render_prompt, text, options, callback)
        done.wait()
        log.info("on_prompt response: %s", holder[0])
        return holder[0]

    def _render_prompt(self, text: str, options: list[ClientOption],
                       callback) -> None:
        self._prompt_title.config(text=text)
        self._clear(self._prompt_buttons)
        for opt in options:
            label = self._option_label(opt)
            tk.Button(
                self._prompt_buttons, text=label, anchor="w", justify="left",
                bg="#444444", fg=TEXT_COLOR, activebackground="#555555",
                activeforeground=TEXT_COLOR, relief="flat",
                wraplength=280, padx=8, pady=4,
                command=lambda o=opt: self._answer(callback, o),
            ).pack(fill="x", pady=2)

    def _answer(self, callback, opt: ClientOption) -> None:
        self._prompt_title.config(text="(waiting)")
        self._clear(self._prompt_buttons)
        callback(opt)

    def _option_label(self, opt: ClientOption) -> str:
        match opt["type"]:
            case "text":
                return opt["text"]
            case "card":
                e = self._cards.get(opt["uid"])
                return e["display_name"] if e else f"uid:{opt['uid']}"
            case "slot":
                return f"slot:{opt['uid']}"
            case "weapon_slot":
                return f"weapon:{opt['uid']}"
            case _:
                return str(opt)

    def on_notify(self, text: str) -> None:
        log.info("on_notify: %s", text)
        self.root.after(0, self._show_notify, text)

    def _show_notify(self, text: str) -> None:
        self._notify_text.config(state="normal")
        self._notify_text.insert("end", text + "\n")
        self._notify_text.see("end")
        self._notify_text.config(state="disabled")

    # ── connection loop ────────────────────────────────────────

    def run(self, host: str, port: int) -> None:
        sock = socket(AF_INET, SOCK_STREAM)
        sock.connect((host, port))
        log.info("Connected to %s:%d", host, port)
        self._conn = TCPConnection(sock)

        Thread(target=self._recv_loop, daemon=True, name="recv").start()

        try:
            self.root.mainloop()
        finally:
            try:
                if self._conn is not None:
                    self._conn.close()
            except (ConnectionError, OSError):
                pass

    def _recv_loop(self) -> None:
        assert self._conn is not None
        try:
            while True:
                msg = self._conn.recv()
                log.debug("recv: type=%s", msg["type"])
                match msg["type"]:
                    case "catalog":
                        self.on_catalog(msg["cards"])
                    case "state":
                        self.on_state(msg["view"])
                    case "prompt":
                        # Per-prompt worker thread keeps the recv loop free
                        # to drain state updates while the user is thinking.
                        Thread(target=self._handle_prompt, args=(msg,),
                               daemon=True, name="prompt-worker").start()
                    case "notify":
                        self.on_notify(msg["text"])
                    case "close":
                        log.info("Server closed the connection")
                        self.root.after(0, self._show_notify,
                                        "Server closed the connection.")
                        return
        except ConnectionError:
            log.warning("Disconnected from server")
            self.root.after(0, self._show_notify, "Disconnected from server.")

    def _handle_prompt(self, msg: dict) -> None:
        chosen = self.on_prompt(msg["text"], msg["options"])
        with self._send_lock:
            try:
                assert self._conn is not None
                self._conn.send({"type": "response", "option": chosen})
            except (ConnectionError, OSError) as e:
                log.warning("send response failed: %s", e)

    def _on_window_close(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except (ConnectionError, OSError):
            pass
        self.root.destroy()


def _setup_logging():
    import os, datetime
    os.makedirs("logs/client", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pid = os.getpid()
    filename = f"logs/client/{ts}_{pid}_gui.log"
    handler = FileHandler(filename, mode="w")
    handler.setFormatter(Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(DEBUG)


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
    _setup_logging()
    GUIGameClient().run(host, port)
