"""
Serialization layer for the wire boundary.

Cards, slots, and weapon slots are all identified on the wire by their
name field. No synthetic UIDs are needed — names are baked into the
engine objects at construction time.

The catalog maps names to metadata (display_name, types, etc. for cards;
owner/role for slots; owner/index for weapon slots). State updates and
prompt options reference names directly.
"""

from core.type import (
    Card, GameState, PID, Slot, WeaponSlot, Phase,
    PlayerView, Option, Event, GameResult,
    CardOption, SlotOption, WeaponSlotOption, TextOption,
    CardMoved, SlotTransferred, HPChanged, SlotShuffled, PlayerDied, PhaseChanged, GameEnded,
    other,
)

type ClientOption = dict
type ClientPlayerView = dict


class Serializer:
    """Server-side: converts engine objects → wire format."""

    def __init__(self,
                 pid_to_ws: dict[PID, list[WeaponSlot]],
                 slot_visibility: dict[PID, dict[Slot, str]]):
        self._pid_to_ws = pid_to_ws
        self._slot_vis = slot_visibility  # pid → {Slot → "cards"|"count"|"hidden"}

    def option(self, opt: Option) -> dict:
        match opt:
            case TextOption(text):
                return {"type": "text", "text": text}  # pragma: no mutate
            case CardOption(card):
                assert card.slot is not None, "CardOption card must be in a Slot"
                return {
                    "type": "card",  # pragma: no mutate
                    "slot": card.slot.name,  # pragma: no mutate
                    "index": card.slot.cards.index(card),
                }
            case SlotOption(slot):
                return {"type": "slot", "name": slot.name}  # pragma: no mutate
            case WeaponSlotOption(ws):
                return {"type": "weapon_slot", "name": ws.name}  # pragma: no mutate
            case _:
                raise ValueError(f"Unknown option type: {opt}")  # pragma: no mutate

    def _vis(self, slot: Slot | None, pid: PID) -> str:
        if slot is None:
            return "hidden"
        return self._slot_vis.get(pid, {}).get(slot, "hidden")

    def events(self, event_list: list, pid: PID) -> list[dict]:
        result = []
        for event in event_list:
            wire = self._serialize_event(event, pid)
            if wire is not None:
                result.append(wire)
        return result

    def _serialize_event(self, event, pid: PID) -> dict | None:
        match event:
            case CardMoved(_, source, source_index, dest, dest_index):
                src_vis = self._vis(source, pid)
                dst_vis = self._vis(dest, pid)
                if src_vis == "hidden" and dst_vis == "hidden":
                    return None
                return {
                    "type": "card_moved",
                    "source": source.name if source else None,
                    "source_index": source_index,
                    "dest": dest.name,
                    "dest_index": dest_index,
                }
            case SlotTransferred(source, dest, count):
                src_vis = self._vis(source, pid)
                dst_vis = self._vis(dest, pid)
                if src_vis == "hidden" and dst_vis == "hidden":
                    return None
                return {
                    "type": "slot_transferred",
                    "source": source.name,
                    "dest": dest.name,
                    "count": count,
                }
            case HPChanged(target, old_hp, new_hp):
                if target != pid:
                    return None
                return {"type": "hp_changed", "old": old_hp, "new": new_hp}
            case SlotShuffled(slot):
                if self._vis(slot, pid) == "hidden":
                    return None
                return {"type": "slot_shuffled", "slot": slot.name}
            case PlayerDied(target):
                return {"type": "player_died", "target": target.name}
            case PhaseChanged(phase):
                return {"type": "phase_changed", "phase": phase.name if phase else None}
            case GameEnded(result):
                return {
                    "type": "game_ended",
                    "winners": [p.name for p in result.winners],
                    "outcome": result.outcome.name,
                }
            case _:
                return None

    def player_view(self, view: PlayerView, pid: PID) -> dict:
        opp = other(pid)
        p_pre = pid.name.lower()
        o_pre = opp.name.lower()

        def _cards(cards: list[Card]) -> list[str]:
            return [c.name for c in cards]

        slots: dict[str, list[str] | int] = {}

        # Own visible slots
        slots[f"{p_pre}_hand"] = _cards(view.hand)
        slots[f"{p_pre}_equipment"] = _cards(view.equipment)
        slots[f"{p_pre}_sidebar"] = _cards(view.sidebar)
        slots[f"{p_pre}_action_field_top_distant"] = _cards(view.action_field_top_distant)
        slots[f"{p_pre}_action_field_top_hidden"] = _cards(view.action_field_top_hidden)
        slots[f"{p_pre}_action_field_bottom_hidden"] = _cards(view.action_field_bottom_hidden)
        slots[f"{p_pre}_action_field_bottom_distant"] = _cards(view.action_field_bottom_distant)

        # Own count-only slots
        slots[f"{p_pre}_deck"] = view.deck_size
        slots[f"{p_pre}_refresh"] = view.refresh_size
        slots[f"{p_pre}_discard"] = view.discard_size

        # Opponent fog-of-war
        slots[f"{o_pre}_deck"] = view.opp_deck_size
        slots[f"{o_pre}_action_field_top_distant"] = _cards(view.opp_action_field_top_distant)
        slots[f"{o_pre}_action_field_bottom_distant"] = _cards(view.opp_action_field_bottom_distant)

        # Own weapon holders + killstacks (public to the owner — card lists of length 0 or N)
        for i, (card, _, killstack) in enumerate(view.weapons):
            slots[f"{p_pre}_ws_{i}_weapon"] = [card.name] if card is not None else []
            slots[f"{p_pre}_ws_{i}_killstack"] = _cards(killstack)

        # Shared
        slots["guard_deck"] = view.guard_deck_size

        gr = view.game_result
        game_result = None if gr is None else {
            "winners": [p.name for p in gr.winners],
            "outcome": gr.outcome.name,
        }

        return {
            "hp": view.hp,
            "slots": slots,
            "current_phase": view.current_phase.name if view.current_phase else None,
            "priority": view.priority.name,
            "game_result": game_result,
        }


class Accumulator:
    """Walks a GameState after setup, catalogs all card templates,
    Slots, and WeaponSlots by their names."""

    def __init__(self, g: GameState):
        self._card_catalog: dict[str, dict] = {}
        # (owner, role, name)
        self._slot_roles: list[tuple[PID | None, str, str]] = []
        # (owner, role, name) for weapon slots
        self._ws_roles: list[tuple[PID, str, str]] = []
        self._pid_to_ws: dict[PID, list[WeaponSlot]] = {PID.RED: [], PID.BLUE: []}
        # slot obj → (owner, role)
        self._slot_info: dict[Slot, tuple[PID | None, str]] = {}

        self._scan(g)

    def _register_template(self, card: Card) -> None:
        if card.name not in self._card_catalog:
            self._card_catalog[card.name] = {
                "name": card.name,  # pragma: no mutate
                "display_name": card.display_name,  # pragma: no mutate
                "text": card.text,  # pragma: no mutate
                "level": card.level,
                "types": [t.name for t in card.types],
                "is_elusive": card.is_elusive,
                "is_first": card.is_first,
            }

    def _register_slot(self, slot: Slot, owner: PID | None, role: str) -> None:
        self._slot_roles.append((owner, role, slot.name))
        self._slot_info[slot] = (owner, role)
        for card in slot.cards:
            self._register_template(card)

    def _register_ws(self, ws: WeaponSlot, owner: PID, role: str) -> None:
        self._ws_roles.append((owner, role, ws.name))
        self._pid_to_ws[owner].append(ws)
        self._register_slot(ws._weapon_slot, owner, f"{role}_weapon")
        self._register_slot(ws.killstack, owner, f"{role}_killstack")

    def _scan(self, g: GameState) -> None:
        for pid in PID:
            p = g.players[pid]
            for slot, role in [
                (p.deck, "deck"), (p.refresh, "refresh"), (p.discard, "discard"),
                (p.hand, "hand"), (p.sidebar, "sidebar"), (p.equipment, "equipment"),
            ]:
                self._register_slot(slot, pid, role)
            for slot, role in [
                (p.action_field.top_distant, "action_field_top_distant"),
                (p.action_field.top_hidden, "action_field_top_hidden"),
                (p.action_field.bottom_hidden, "action_field_bottom_hidden"),
                (p.action_field.bottom_distant, "action_field_bottom_distant"),
            ]:
                self._register_slot(slot, pid, role)
            for i, ws in enumerate(p.weapon_slots):
                self._register_ws(ws, pid, f"ws_{i}")
        self._register_slot(g.guard_deck, None, "guard_deck")

    # Roles whose cards are visible to the owning player
    _CARDS_VISIBLE_OWN = frozenset({
        "hand", "equipment", "sidebar",
        "action_field_top_distant", "action_field_top_hidden",
        "action_field_bottom_hidden", "action_field_bottom_distant",
    })
    # Roles whose cards are visible to the opponent
    _CARDS_VISIBLE_OPP = frozenset({
        "action_field_top_distant", "action_field_bottom_distant",
    })
    # Roles whose count is visible to the owning player
    _COUNT_VISIBLE_OWN = frozenset({
        "deck", "refresh", "discard",
    })
    # Roles whose count is visible to the opponent
    _COUNT_VISIBLE_OPP = frozenset({
        "deck",
    })

    def _build_visibility(self) -> dict[PID, dict[Slot, str]]:
        vis: dict[PID, dict[Slot, str]] = {pid: {} for pid in PID}
        for slot, (owner, role) in self._slot_info.items():
            for pid in PID:
                if owner == pid or owner is None:
                    # Own slot (or shared). Own weapon holders + killstacks are public.
                    if (role in self._CARDS_VISIBLE_OWN
                            or role.endswith(("_killstack", "_weapon"))):
                        vis[pid][slot] = "cards"
                    else:
                        vis[pid][slot] = "count"
                else:
                    # Opponent's slot
                    if role in self._CARDS_VISIBLE_OPP:
                        vis[pid][slot] = "cards"
                    elif role in self._COUNT_VISIBLE_OPP:
                        vis[pid][slot] = "count"
                    else:
                        vis[pid][slot] = "hidden"
        return vis

    def serializer(self) -> Serializer:
        return Serializer(
            {pid: list(ws) for pid, ws in self._pid_to_ws.items()},
            self._build_visibility(),
        )

    def catalog(self, pid: PID) -> dict:
        """Per-player catalog for session init.

        Cards, slots, and weapon_slots are all keyed by wire name,
        mapping to a description dict with owner and role."""
        def _owner_label(owner: PID | None) -> str:  # pragma: no mutate
            if owner is None:
                return "shared"  # pragma: no mutate
            return "self" if owner == pid else "opponent"  # pragma: no mutate

        slots: dict[str, dict] = {}  # pragma: no mutate
        for owner, role, name in self._slot_roles:
            slots[name] = {"owner": _owner_label(owner), "role": role}  # pragma: no mutate

        weapon_slots: dict[str, dict] = {}  # pragma: no mutate
        for owner, role, name in self._ws_roles:
            weapon_slots[name] = {"owner": _owner_label(owner), "role": role}  # pragma: no mutate

        return {
            "cards": self._card_catalog,
            "slots": slots,
            "weapon_slots": weapon_slots,
        }
