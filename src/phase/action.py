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
        for pid in PID:
            p = g.players[pid]
            p.first_play_done = False
            p.action_plays_left = 3

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
                if g.is_over or any(g.players[pid].is_dead for pid in PID):
                    return

            yield from _action_play(current)(g)
            p.action_plays_left -= 1
            p.first_play_done = True

            if g.is_over or any(g.players[pid].is_dead for pid in PID):
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

        can_run = True
        can_call_guards = (
            p.alignment == Alignment.GOOD
            and _find_role_card(p) is not None
        )

        if not (can_run or can_call_guards): return

        pb = (PromptBuilder("Last Resort?")  # pragma: no mutate
              .add(TextOption("None"))  # pragma: no mutate
              .add_if(can_run, TextOption("Run"))  # pragma: no mutate
              .add_if(can_call_guards, TextOption("Call the Guards")))  # pragma: no mutate

        response = yield pb.build(pid)  # pragma: no mutate
        match response[pid]:
            case TextOption("None"): return
            case TextOption("Run"): yield from _run(pid)(g)  # pragma: no mutate
            case TextOption("Call the Guards"): yield from _call_guards(pid)(g)  # pragma: no mutate

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
        opp = other(pid)  # pragma: no mutate
        sidebar = g.players[opp].sidebar

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
            pb = (PromptBuilder(f"Recycle {card.display_name}?")  # pragma: no mutate
                  .add(TextOption("Keep"))  # pragma: no mutate
                  .add(TextOption("Recycle"))  # pragma: no mutate
                  .context(CardOption(card)))  # pragma: no mutate
            response = yield pb.build(opp)  # pragma: no mutate
            if response[opp] == TextOption("Recycle"):
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
) -> list[tuple[Slot, str, bool, bool, bool]]:
    """Return (slot, label, is_opponent_field, is_distant, is_hidden) for each legal choice."""
    choices: list[tuple[Slot, str, bool, bool, bool]] = []

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
        choices.append((slot, label, False, False, False))

    opp_pid = other(pid)
    opp = g.players[opp_pid].action_field
    _opp_names = [
        (opp.top_distant, "Opponent top distant", True, False),  # pragma: no mutate
        (opp.top_hidden, "Opponent top hidden", False, True),  # pragma: no mutate
        (opp.bottom_hidden, "Opponent bottom hidden", False, True),  # pragma: no mutate
        (opp.bottom_distant, "Opponent bottom distant", True, False),  # pragma: no mutate
    ]
    for slot, label, distant, hidden in _opp_names:
        if slot.is_empty():
            continue
        if g.players[pid].first_play_done and slot.is_first:
            continue
        choices.append((slot, label, True, distant, hidden))

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
            pb = PromptBuilder("Resolve which slot?")  # pragma: no mutate
            for s, _, _, _, _ in choices:
                pb.add(SlotOption(s))  # pragma: no mutate
            response = yield pb.build(pid)  # pragma: no mutate
            chosen = response[pid]
            assert isinstance(chosen, SlotOption)
            slot = chosen.slot
            _, _, is_opp, is_dist, _ = next(c for c in choices if c[0] is slot)

            # Opponent slots require consent
            if is_opp:
                opp_pid = other(pid)  # pragma: no mutate
                cpb = (PromptBuilder("Allow opponent to resolve your slot?")  # pragma: no mutate
                       .add(TextOption("Allow"))  # pragma: no mutate
                       .add(TextOption("Deny"))  # pragma: no mutate
                       .context(SlotOption(slot)))  # pragma: no mutate
                consent = yield cpb.build(opp_pid)  # pragma: no mutate
                if consent[opp_pid] == TextOption("Deny"):
                    continue  # denied → re-pick

                if is_dist:
                    yield from do(Damage(pid, DISTANCE_PENALTY, "distance penalty"))(g)  # pragma: no mutate
                    if p.is_dead:
                        return

            yield from _resolve_slot(pid, slot)(g)
            return

    return effect


# ── Resolution ────────────────────────────────────────────────

def _resolve_slot(pid: PID, slot: Slot) -> Effect:
    """Resolve the top card of the slot repeatedly until it is empty."""
    def effect(g: GameState) -> Negotiation:
        while not slot.is_empty():
            yield from _offer_voluntary_discard(pid)(g)
            yield from do(Resolve(pid, slot.cards[0], "action play"))(g)  # pragma: no mutate
            if g.players[pid].is_dead:
                return
        yield from _offer_voluntary_discard(pid)(g)
    return effect


def _offer_voluntary_discard(pid: PID) -> Effect:
    """Offer the player a chance to discard equipment or weapons."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        while True:
            discardable: list[Card] = list(p.equipment.cards)
            weapon_slots: dict[int, WeaponSlot] = {}
            for ws in p.weapon_slots:
                if ws.weapon is not None:
                    discardable.append(ws.weapon)
                    weapon_slots[id(ws.weapon)] = ws

            if not discardable:
                return

            pb = PromptBuilder("Voluntarily discard?")  # pragma: no mutate
            pb.add_cards(discardable)  # pragma: no mutate
            pb.add(TextOption("Don't discard"))  # pragma: no mutate
            response = yield pb.build(pid)  # pragma: no mutate

            match response[pid]:
                case TextOption("Don't discard"):
                    return
                case CardOption(card):
                    pass
                case _:
                    return
            ws = weapon_slots.get(id(card))
            yield from do(Discard(pid, card, "voluntary discard"))(g)  # pragma: no mutate
            if ws is not None:
                for kill_card in list(ws.killstack.cards):
                    yield from do(Discard(pid, kill_card, "voluntary discard kill pile"))(g)  # pragma: no mutate

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
