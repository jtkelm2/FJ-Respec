from core.type import *
from core.engine import do

HAND_SIZE = 4
MANIPULATION_DEAL = 2


def refresh_phase() -> Effect:
    """
    Refresh Phase:
      1. Shuffle each player's refresh pile into their deck
      2. Deal hand (up to 4 from OTHER player's deck)
      3. Deal action cards (empty_slots - 1 from OWN deck)
      4. Deal manipulation cards (2 from OTHER player's deck)
      5. Flip priority
    """
    def effect(g: GameState) -> Negotiation:
        for pid in PID:
            g.players[pid].is_satiated = True
    
        for pid in PID:
            yield from do(ShuffleRefreshIntoDeck(pid, "refresh phase"))(g)  # pragma: no mutate

        for pid in PID:
            yield from _deal_hand(pid)(g)

        for pid in PID:
            yield from _deal_action_cards(pid)(g)

        for pid in PID:
            yield from _deal_manipulation(pid)(g)
    return effect


# --- Helpers ---

def _deal_hand(pid: PID) -> Effect:
    """Deal cards to pid's hand from the OTHER player's deck, up to HAND_SIZE."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        while not p.is_dead and len(g.players[pid].hand.cards) < HAND_SIZE:
            yield from do(Draw(pid, "refresh deal hand"))(g)  # pragma: no mutate
    return effect


def _deal_action_cards(pid: PID) -> Effect:
    """Deal (empty_slots - 1) cards from pid's OWN deck into their action field."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        empty = [s for s in p.action_field.slots_in_fill_order() if s.is_empty()][:-1]
        for slot in empty:
            yield from do(EnsureDeck(pid, "action card deal"))(g)  # pragma: no mutate
            yield from do(Slot2Slot(p.deck,slot, "action card deal"))(g)  # pragma: no mutate
    return effect


def _deal_manipulation(pid: PID) -> Effect:
    """Deal 2 manipulation cards from the OTHER player's deck."""
    def effect(g: GameState) -> Negotiation:
        deck = g.players[other(pid)].deck
        mf = g.players[pid].sidebar
        for _ in range(MANIPULATION_DEAL):
            yield from do(EnsureDeck(other(pid)))(g)
            yield from do(Slot2Slot(deck, mf, "deal to manipulation field"))(g)  # pragma: no mutate
    return effect
