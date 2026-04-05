from core.type import *
from core.engine import do

DISTANCE_PENALTY = 3


def action_phase() -> Effect:
    """
    Action Phase:
      Players alternate resolving action slots (priority player first).
      Each player makes p.action_plays_left action plays.
      Before a player's first action play, they may make a Last Resort play.
      After all plays, Elusive cards on the action field are refreshed.
    """
    def effect(g: GameState) -> Negotiation:
        current = g.priority

        while not all(
            g.players[pid].action_plays_left <= 0 or g.players[pid].is_dead
            for pid in PID
        ):
            p = g.players[current]

            if p.is_dead or p.action_plays_left <= 0:
                current = other(current)
                continue

            # Offer last resort before first action play
            if not p.first_play_done:
                yield from _offer_last_resort(current)(g)
                if any(g.players[pid].is_dead for pid in PID):
                    return

            yield from _action_play(current)(g)
            p.action_plays_left -= 1
            p.first_play_done = True

            if any(g.players[pid].is_dead for pid in PID):
                return

            current = other(current)

        # Refresh Elusive cards remaining on the action field
        for pid in PID:
            for slot in g.players[pid].action_field.slots_in_fill_order():
                for card in list(slot.cards):
                    if card.is_elusive:
                        yield from do(Refresh(card, pid, "elusive end of action phase"))(g)  # pragma: no mutate
        
        yield from do(FlipPriority("refresh phase"))(g)  # pragma: no mutate
    return effect


# ── Last Resorts ──────────────────────────────────────────────

def _offer_last_resort(pid: PID) -> Effect:
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]

        options = ["None"]  # pragma: no mutate
        can_run = True
        can_call_guards = (
            p.alignment == Alignment.GOOD
            and _find_role_card(p) is not None
        )

        if can_run:
            options.append("Run")  # pragma: no mutate
        if can_call_guards:
            options.append("Call the Guards")  # pragma: no mutate

        if len(options) == 1:
            return

        response = yield Ask(pid, "Last Resort?", options)  # pragma: no mutate
        choice = response[pid]

        if choice == 0:
            return
        label = options[choice]
        if label == "Run":  # pragma: no mutate
            yield from _run(pid)(g)
        elif label == "Call the Guards":  # pragma: no mutate
            yield from _call_guards(pid)(g)

    return effect


def _find_role_card(p: PlayerState) -> Card | None:
    role_name = p.role.name.lower()
    return next(
        (c for c in p.equipment.cards if c.name == role_name),
        None,
    )


def _run(pid: PID) -> Effect:
    """Running: refresh own action field, opponent reviews replacements."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        opp = other(pid)
        sidebar = p.sidebar

        # 1. Refresh each card on your action slots
        for slot in p.action_field.slots_in_fill_order():
            for card in list(slot.cards):
                yield from do(Refresh(card, pid, "running"))(g)  # pragma: no mutate

        # 2. Draw one card per action slot into sidebar
        num_slots = len(p.action_field.slots_in_fill_order())
        for _ in range(num_slots):
            yield from do(EnsureDeck(pid, "running"))(g)  # pragma: no mutate
            if p.is_dead:
                return
            yield from do(Slot2Slot(p.deck, sidebar, "running draw"))(g)  # pragma: no mutate

        # 3. Opponent may recycle each card
        for card in list(sidebar.cards):
            response = yield Ask(opp, f"Recycle {card.display_name}?", ["Keep", "Recycle"])  # pragma: no mutate
            if response[opp] == 1:
                yield from do(Refresh(card, pid, "running recycle"))(g)  # pragma: no mutate
                yield from do(EnsureDeck(pid, "running recycle"))(g)  # pragma: no mutate
                if p.is_dead:
                    return
                yield from do(Slot2Slot(p.deck, sidebar, "running recycle draw"))(g)  # pragma: no mutate

        # 4. Shuffle sidebar and deal into empty action field slots
        yield from do(Shuffle(sidebar, "running deal"))(g)  # pragma: no mutate
        for slot in p.action_field.slots_in_fill_order():
            if slot.is_empty():
                yield from do(Slot2Slot(sidebar, slot, "running deal"))(g)  # pragma: no mutate

    return effect


def _call_guards(pid: PID) -> Effect:
    """Calling the Guards: discard role card, disarm opponent, deploy guards."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        opp_pid = other(pid)
        opp = g.players[opp_pid]

        # 1. Discard role card
        role_card = _find_role_card(p)
        assert role_card is not None
        yield from do(Discard(pid, role_card, "calling the guards"))(g)  # pragma: no mutate

        # 2. Disarm the other player
        yield from do(Disarm(opp_pid, "calling the guards"))(g)  # pragma: no mutate

        # 3. Place guards on opponent's action field
        for slot in opp.action_field.slots_in_fill_order():
            if not g.guard_deck.is_empty():
                yield from do(Slot2Slot(g.guard_deck, slot, "guards"))(g)  # pragma: no mutate

    return effect


# ── Slot selection ────────────────────────────────────────────

def _legal_slot_choices(
    pid: PID, g: GameState
) -> list[tuple[Slot, str, bool, bool]]:
    """Return (slot, label, is_opponent_field, is_distant) for each legal choice."""
    choices: list[tuple[Slot, str, bool, bool]] = []

    own = g.players[pid].action_field
    _own_names = [
        (own.top_distant, "Your top distant"),  # pragma: no mutate
        (own.top_hidden, "Your top hidden"),  # pragma: no mutate
        (own.bottom_hidden, "Your bottom hidden"),  # pragma: no mutate
        (own.bottom_distant, "Your bottom distant"),  # pragma: no mutate
    ]
    for slot, label in _own_names:
        if slot.is_empty():
            continue
        if g.players[pid].first_play_done and slot.is_first:
            continue
        choices.append((slot, label, False, False))

    opp_pid = other(pid)
    opp = g.players[opp_pid].action_field
    _opp_names = [
        (opp.top_distant, "Opponent top distant", True),  # pragma: no mutate
        (opp.top_hidden, "Opponent top hidden", False),  # pragma: no mutate
        (opp.bottom_hidden, "Opponent bottom hidden", False),  # pragma: no mutate
        (opp.bottom_distant, "Opponent bottom distant", True),  # pragma: no mutate
    ]
    for slot, label, distant in _opp_names:
        if slot.is_empty():
            continue
        if g.players[pid].first_play_done and slot.is_first:
            continue
        choices.append((slot, label, True, distant))

    return choices


# ── Action play ───────────────────────────────────────────────

def _action_play(pid: PID) -> Effect:
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        choices = _legal_slot_choices(pid, g)

        # Fallback: no legal slots anywhere → resolve top of own deck
        if not choices:
            yield from _resolve_top_of_deck(pid)(g)
            return

        while True:
            labels = [_slot_label(s, lbl) for s, lbl, _, _ in choices]  # pragma: no mutate
            response = yield Ask(pid, "Resolve which slot?", labels)  # pragma: no mutate
            idx = response[pid]
            slot, _, is_opp, is_dist = choices[idx]

            # Opponent slots require consent
            if is_opp:
                opp_pid = other(pid)
                consent = yield Ask(opp_pid, f"Allow opponent to resolve your slot?", ["Allow", "Deny"])  # pragma: no mutate
                if consent[opp_pid] == 1:
                    continue  # denied → re-pick

                if is_dist:
                    yield from do(Damage(pid, DISTANCE_PENALTY, "distance penalty"))(g)  # pragma: no mutate
                    if p.is_dead:
                        return

            yield from _resolve_slot(pid, slot)(g)
            return

    return effect


def _slot_label(slot: Slot, prefix: str) -> str:
    card_names = ", ".join(c.display_name for c in slot.cards)  # pragma: no mutate
    return f"{prefix}: [{card_names}]"  # pragma: no mutate


# ── Resolution ────────────────────────────────────────────────

def _resolve_slot(pid: PID, slot: Slot) -> Effect:
    """Resolve the top card of the slot repeatedly until it is empty."""
    def effect(g: GameState) -> Negotiation:
        while not slot.is_empty():
            yield from do(Resolve(pid, slot.cards[0], "action play"))(g)  # pragma: no mutate
            if g.players[pid].is_dead:
                return
    return effect


def _resolve_top_of_deck(pid: PID) -> Effect:
    """Fallback when no legal action slots exist: resolve one card off own deck."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        yield from do(EnsureDeck(pid, "top of deck resolve"))(g)  # pragma: no mutate
        if p.is_dead:
            return
        yield from do(Slot2Slot(p.deck, p.sidebar, "draw for resolve"))(g)  # pragma: no mutate
        card = p.sidebar.cards[0]
        yield from do(Resolve(pid, card, "top of deck"))(g)  # pragma: no mutate
    return effect
