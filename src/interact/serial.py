"""
Serialization layer for the wire boundary.

Translates between engine object references (Card, Slot, WeaponSlot)
and stable integer UIDs for the wire protocol. The engine never sees UIDs.
"""

from core.type import (
    Card, CardType, GameState, PID, Slot, WeaponSlot,
    PlayerView, PromptHalf, Option,
    CardOption, SlotOption, WeaponSlotOption, TextOption,
    GameResult, Outcome, other,
)

type UID = int
type ClientOption = dict
type ClientPlayerView = dict


class Serializer:
    """Server-side: converts engine objects → UIDs for the wire."""

    def __init__(self, card_key: dict[Card, UID],
                 slot_key: dict[Slot, UID],
                 ws_key: dict[WeaponSlot, UID]):
        self._card = card_key
        self._slot = slot_key
        self._ws = ws_key

    def card(self, c: Card) -> UID:
        return self._card[c]

    def slot(self, s: Slot) -> UID:
        return self._slot[s]

    def weapon_slot(self, ws: WeaponSlot) -> UID:
        return self._ws[ws]

    def option(self, opt: Option) -> dict:
        match opt:
            case TextOption(text):
                return {"type": "text", "text": text}
            case CardOption(card):
                return {"type": "card", "uid": self.card(card)}
            case SlotOption(slot):
                return {"type": "slot", "uid": self.slot(slot)}
            case WeaponSlotOption(ws):
                return {"type": "weapon_slot", "uid": self.weapon_slot(ws)}
            case _:
                raise ValueError(f"Unknown option type: {opt}")

    def prompt_half(self, half: PromptHalf) -> dict:
        return {
            "text": half.text,
            "options": [self.option(o) for o in half.options],
        }

    def player_view(self, view: PlayerView) -> dict:
        def _card_uids(cards: list[Card]) -> list[UID]:
            return [self.card(c) for c in cards]

        weapons = []
        for w, sharpness, kills in view.weapons:
            weapons.append([self.card(w) if w is not None else None, sharpness, kills])

        opp_weapons = [[s, k] for s, k in view.opp_weapons]

        gr = view.game_result
        game_result = None if gr is None else {
            "winners": [p.name for p in gr.winners],
            "outcome": gr.outcome.name,
        }

        return {
            "hp": view.hp,
            "hand": _card_uids(view.hand),
            "equipment": _card_uids(view.equipment),
            "weapons": weapons,
            "deck_size": view.deck_size,
            "refresh_size": view.refresh_size,
            "discard_size": view.discard_size,
            "action_field_top_distant": _card_uids(view.action_field_top_distant),
            "action_field_top_hidden": _card_uids(view.action_field_top_hidden),
            "action_field_bottom_hidden": _card_uids(view.action_field_bottom_hidden),
            "action_field_bottom_distant": _card_uids(view.action_field_bottom_distant),
            "sidebar": _card_uids(view.sidebar),
            "opp_equipment_count": view.opp_equipment_count,
            "opp_weapons": opp_weapons,
            "opp_deck_size": view.opp_deck_size,
            "opp_refresh_size": view.opp_refresh_size,
            "opp_discard_size": view.opp_discard_size,
            "opp_action_field_top_distant": _card_uids(view.opp_action_field_top_distant),
            "opp_action_field_top_hidden_count": view.opp_action_field_top_hidden_count,
            "opp_action_field_bottom_hidden_count": view.opp_action_field_bottom_hidden_count,
            "opp_action_field_bottom_distant": _card_uids(view.opp_action_field_bottom_distant),
            "priority": view.priority.name,
            "guard_deck_size": view.guard_deck_size,
            "game_result": game_result,
        }


class Deserializer:
    """Client-side: converts UIDs → engine objects."""

    def __init__(self, card_key: dict[UID, Card],
                 slot_key: dict[UID, Slot],
                 ws_key: dict[UID, WeaponSlot]):
        self._card = card_key
        self._slot = slot_key
        self._ws = ws_key

    @classmethod
    def from_catalog(cls, catalog: list[dict]) -> "Deserializer":
        """Build from a card catalog received over the wire."""
        cards: dict[UID, Card] = {}
        for entry in catalog:
            c = Card(
                name=entry["name"],
                display_name=entry["display_name"],
                text=entry["text"],
                level=entry["level"],
                types=tuple(CardType[t] for t in entry["types"]),
                is_elusive=entry["is_elusive"],
                is_first=entry["is_first"],
            )
            cards[entry["uid"]] = c
        return cls(cards, {}, {})

    def card(self, uid: UID) -> Card:
        return self._card[uid]

    def slot(self, uid: UID) -> Slot:
        return self._slot[uid]

    def weapon_slot(self, uid: UID) -> WeaponSlot:
        return self._ws[uid]

    def option(self, data: dict) -> Option:
        match data["type"]:
            case "text":
                return TextOption(data["text"])
            case "card":
                return CardOption(self.card(data["uid"]))
            case "slot":
                return SlotOption(self.slot(data["uid"]))
            case "weapon_slot":
                return WeaponSlotOption(self.weapon_slot(data["uid"]))
            case _:
                raise ValueError(f"Unknown option type: {data['type']}")

    def player_view(self, data: dict) -> PlayerView:
        def _cards(uids: list[UID]) -> list[Card]:
            return [self.card(u) for u in uids]

        def _weapon(w):
            return (self.card(w[0]) if w[0] is not None else None, w[1], w[2])

        gr = data["game_result"]
        game_result = None if gr is None else GameResult(
            winners=tuple(PID[w] for w in gr["winners"]),
            outcome=Outcome[gr["outcome"]],
        )

        return PlayerView(
            hp=data["hp"],
            hand=_cards(data["hand"]),
            equipment=_cards(data["equipment"]),
            weapons=[_weapon(w) for w in data["weapons"]],
            deck_size=data["deck_size"],
            refresh_size=data["refresh_size"],
            discard_size=data["discard_size"],
            action_field_top_distant=_cards(data["action_field_top_distant"]),
            action_field_top_hidden=_cards(data["action_field_top_hidden"]),
            action_field_bottom_hidden=_cards(data["action_field_bottom_hidden"]),
            action_field_bottom_distant=_cards(data["action_field_bottom_distant"]),
            sidebar=_cards(data["sidebar"]),
            opp_equipment_count=data["opp_equipment_count"],
            opp_weapons=[tuple(w) for w in data["opp_weapons"]],
            opp_deck_size=data["opp_deck_size"],
            opp_refresh_size=data["opp_refresh_size"],
            opp_discard_size=data["opp_discard_size"],
            opp_action_field_top_distant=_cards(data["opp_action_field_top_distant"]),
            opp_action_field_top_hidden_count=data["opp_action_field_top_hidden_count"],
            opp_action_field_bottom_hidden_count=data["opp_action_field_bottom_hidden_count"],
            opp_action_field_bottom_distant=_cards(data["opp_action_field_bottom_distant"]),
            priority=PID[data["priority"]],
            guard_deck_size=data["guard_deck_size"],
            game_result=game_result,
        )


class Accumulator:
    """Walks a GameState after setup, assigns UIDs to every Card, Slot, and WeaponSlot."""

    def __init__(self, g: GameState):
        self._next_uid: UID = 0
        self._card_to_uid: dict[Card, UID] = {}
        self._uid_to_card: dict[UID, Card] = {}
        self._slot_to_uid: dict[Slot, UID] = {}
        self._uid_to_slot: dict[UID, Slot] = {}
        self._ws_to_uid: dict[WeaponSlot, UID] = {}
        self._uid_to_ws: dict[UID, WeaponSlot] = {}
        self._scan(g)

    def _assign(self) -> UID:
        uid = self._next_uid
        self._next_uid += 1
        return uid

    def _register_card(self, card: Card) -> None:
        if card not in self._card_to_uid:
            uid = self._assign()
            self._card_to_uid[card] = uid
            self._uid_to_card[uid] = card

    def _register_slot(self, slot: Slot) -> None:
        if slot not in self._slot_to_uid:
            uid = self._assign()
            self._slot_to_uid[slot] = uid
            self._uid_to_slot[uid] = slot
            for card in slot.cards:
                self._register_card(card)

    def _register_ws(self, ws: WeaponSlot) -> None:
        if ws not in self._ws_to_uid:
            uid = self._assign()
            self._ws_to_uid[ws] = uid
            self._uid_to_ws[uid] = ws
            if ws.weapon is not None:
                self._register_card(ws.weapon)
            for card in ws.killstack.cards:
                self._register_card(card)

    def _scan(self, g: GameState) -> None:
        for pid in PID:
            p = g.players[pid]
            for slot in [p.deck, p.refresh, p.discard, p.hand,
                         p.sidebar, p.equipment]:
                self._register_slot(slot)
            for slot in p.action_field.slots_in_fill_order():
                self._register_slot(slot)
            for ws in p.weapon_slots:
                self._register_ws(ws)
        self._register_slot(g.guard_deck)

    def serializer(self) -> Serializer:
        return Serializer(dict(self._card_to_uid),
                          dict(self._slot_to_uid),
                          dict(self._ws_to_uid))

    def deserializer(self) -> Deserializer:
        return Deserializer(dict(self._uid_to_card),
                            dict(self._uid_to_slot),
                            dict(self._uid_to_ws))

    def catalog(self) -> list[dict]:
        """Card catalog for session init — sent to client once."""
        result = []
        for uid in sorted(self._uid_to_card):
            c = self._uid_to_card[uid]
            result.append({
                "uid": uid,
                "name": c.name,
                "display_name": c.display_name,
                "text": c.text,
                "level": c.level,
                "types": [t.name for t in c.types],
                "is_elusive": c.is_elusive,
                "is_first": c.is_first,
            })
        return result

    def register_card(self, card: Card) -> UID:
        """Register a card created mid-game. Returns its UID."""
        self._register_card(card)
        return self._card_to_uid[card]
