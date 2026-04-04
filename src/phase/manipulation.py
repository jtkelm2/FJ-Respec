from core.type import *
from core.engine import do, simultaneously


def manipulation_phase() -> Effect:
    """
    Manipulation Phase (fully async of either player):
      Each player independently:
        1. Chooses: Manipulate or Dump
        2. Executes that choice (swap loop + force, or discard/refresh hand)
        3. Post-manipulation: mix third card, shuffle, deal one to opponent, clean up
    """
    def player_effect(pid) -> Effect:
        def eff(g):
            forcing = {'val': False}
            response = yield Ask(pid, "Choose: Manipulate or Dump?", ["Manipulate", "Dump"])  # pragma: no mutate
            if response[pid] == 0:
                yield from _manipulate(pid, forcing)(g)  # pragma: no mutate
            else:
                yield from _dump(pid)(g)  # pragma: no mutate
            yield from _post_manipulation(pid, forcing['val'])(g)
        return eff

    return simultaneously({pid: player_effect(pid) for pid in PID})


# --- Helpers ---

def _manipulate(pid: PID, forcing: dict[str,bool]) -> Effect:
    """Swap cards between manipulation field and hand; optionally force."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]

        # Swap loop
        while True:
            mf_cards = p.manipulation_field.cards
            hand_cards = p.hand.cards

            options = [c.display_name for c in mf_cards] + ["Done"]  # pragma: no mutate
            response = yield Ask(pid, "Choose a card from manipulation field to swap, or Done:", options)  # pragma: no mutate
            choice = response[pid]

            if choice >= len(mf_cards):
                break

            mf_card = mf_cards[choice]

            hand_options = [c.display_name for c in hand_cards]  # pragma: no mutate
            response = yield Ask(pid, "Choose a card from hand to swap with:", hand_options)  # pragma: no mutate
            hand_card = hand_cards[response[pid]]

            # Swap: move each card to the other's slot
            yield from do(SlotCard(mf_card, p.hand, "manipulation swap"))(g)  # pragma: no mutate
            yield from do(SlotCard(hand_card, p.manipulation_field, "manipulation swap"))(g)  # pragma: no mutate

        # Force option: discard equipment to choose which card to send
        equipment_cards = p.equipment.cards
        if equipment_cards:
            options = ["No"] + [f"Discard {c.display_name}" for c in equipment_cards]  # pragma: no mutate
            response = yield Ask(pid, "Force? (Discard equipment to choose which card to send)", options)  # pragma: no mutate
            choice = response[pid]
            if choice > 0:
                equip = equipment_cards[choice - 1]
                yield from do(Discard(pid, equip, "forcing"))(g)  # pragma: no mutate
                forcing['val'] = True

    return effect


def _dump(pid: PID) -> Effect:
    """Discard or refresh each card in hand. Elusive cards must be refreshed."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        other_pid = other(pid)

        for card in list(p.hand.cards):
            if card.is_elusive:
                yield from do(Refresh(card, other_pid, "dump elusive"))(g)  # pragma: no mutate
            else:
                response = yield Ask(pid, f"{card.display_name}:", ["Discard", "Refresh"])  # pragma: no mutate
                if response[pid] == 0:
                    yield from do(Discard(other_pid, card, "dump discard"))(g)  # pragma: no mutate
                else:
                    yield from do(Refresh(card, other_pid, "dump refresh"))(g)  # pragma: no mutate

    return effect


def _post_manipulation(pid: PID, is_forcing: bool) -> Effect:
    """
    Post-manipulation steps:
      1. (Flip cards in manipulation field — no-op in headless engine)
      2. Draw one card from other player's deck into manipulation field
      3. Shuffle manipulation field; deal one to other player's open action slot
      4. Refresh remaining manipulation field cards
      5. Refresh any elusive cards from hand
    """
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        other_pid = other(pid)
        other_p = g.players[other_pid]

        # Step 2: draw from other's deck into manipulation field
        yield from do(EnsureDeck(other_pid, "manipulation deal"))(g)  # pragma: no mutate
        yield from do(Slot2Slot(other_p.deck, p.manipulation_field, "manipulation deal"))(g)  # pragma: no mutate

        # Step 3: shuffle manipulation field, deal one to other's open action slot
        yield from do(Shuffle(p.manipulation_field, "manipulation shuffle"))(g)  # pragma: no mutate

        open_slots = [s for s in other_p.action_field.slots_in_fill_order() if s.is_empty()]
        for slot in open_slots:
            if is_forcing:
                mf_cards = p.manipulation_field.cards
                response = yield Ask(pid, "Choose card to force to opponent:", [c.display_name for c in mf_cards])  # pragma: no mutate
                chosen = mf_cards[response[pid]]
                yield from do(SlotCard(chosen, slot, "forced deal to action field"))(g)  # pragma: no mutate
            else:
                # Already shuffled, so drawing position 0 is effectively random
                yield from do(Slot2Slot(p.manipulation_field, slot, "deal to action field"))(g)  # pragma: no mutate

        # Step 4: refresh remaining manipulation field cards (back to other's refresh pile)
        for card in list(p.manipulation_field.cards):
            yield from do(Refresh(card, other_pid, "refresh manipulation remainder"))(g)  # pragma: no mutate

        # Step 5: refresh any elusive cards still in hand (back to other's refresh pile)
        for card in list(p.hand.cards):
            if card.is_elusive:
                yield from do(Refresh(card, other_pid, "refresh elusive from hand"))(g)  # pragma: no mutate

    return effect
