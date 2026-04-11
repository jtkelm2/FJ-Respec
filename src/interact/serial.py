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
    Card, GameState, PID, Slot, WeaponSlot,
    PlayerView, Option,
    CardOption, SlotOption, WeaponSlotOption, TextOption,
    other,
)

type ClientOption = dict
type ClientPlayerView = dict


class Serializer:
    """Server-side: converts engine objects → wire format."""

    def __init__(self,
                 pid_to_ws: dict[PID, list[WeaponSlot]]):
        self._pid_to_ws = pid_to_ws

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

        # Own weapon killstacks (count-only)
        for i, (_, _, kills) in enumerate(view.weapons):
            slots[f"{p_pre}_ws_{i}_killstack"] = kills

        # Shared
        slots["guard_deck"] = view.guard_deck_size

        # Weapons
        weapons = []
        for ws, (card, sharpness, kills) in zip(self._pid_to_ws[pid], view.weapons):
            weapons.append({
                "name": ws.name,  # pragma: no mutate
                "card": card.name if card is not None else None,
                "sharpness": sharpness,
                "kills": kills,
            })

        gr = view.game_result
        game_result = None if gr is None else {
            "winners": [p.name for p in gr.winners],
            "outcome": gr.outcome.name,
        }

        return {
            "hp": view.hp,
            "slots": slots,
            "weapons": weapons,
            "current_phase": view.current_phase.name if view.current_phase else None,
            "priority": view.priority.name,
            "game_result": game_result,
        }


class Accumulator:
    """Walks a GameState after setup, catalogs all card templates,
    Slots, and WeaponSlots by their names."""

    def __init__(self, g: GameState):
        self._card_catalog: dict[str, dict] = {}
        # (owner, role) → slot name
        self._slot_roles: list[tuple[PID | None, str, str]] = []
        # (owner, ws_name)
        self._ws_roles: list[tuple[PID, str, str]] = []
        self._pid_to_ws: dict[PID, list[WeaponSlot]] = {PID.RED: [], PID.BLUE: []}

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

    def serializer(self) -> Serializer:
        return Serializer(
            {pid: list(ws) for pid, ws in self._pid_to_ws.items()},
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
