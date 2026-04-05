"""Shared test utilities for the Fool's Journey test suite."""

import random
from core.type import (
    GameState, PlayerState, PID, Slot, ActionField,
)
from core.engine import run, do
from core.interpret import AggregateInterpreter, ScriptedInterpreter


def interp(*red_choices, blue=None):
    """Build an interpreter from scripted choice lists."""
    if blue is None:
        blue = []
    return AggregateInterpreter(
        ScriptedInterpreter(list(red_choices)),
        ScriptedInterpreter(list(blue)),
    )


def minimal_game(seed=42):
    """Lightweight GameState with empty slots (no full decks)."""
    return GameState(
        rng=random.Random(seed),
        priority=PID.RED,
        players={PID.RED: PlayerState(), PID.BLUE: PlayerState()},
        guard_deck=Slot(),
        action_field=ActionField(),
    )


def count_all_cards(g):
    """Count every card across all slots in the game. For conservation checks."""
    total = 0
    for pid in PID:
        p = g.players[pid]
        for slot in [p.deck, p.refresh, p.discard, p.hand,
                     p.sidebar, p.equipment]:
            total += len(slot.cards)
        for s in p.action_field.slots_in_fill_order():
            total += len(s.cards)
        for ws in p.weapon_slots:
            total += len(ws._weapon_slot.cards)
            total += len(ws.killstack.cards)
    total += len(g.guard_deck.cards)
    for s in g.action_field.slots_in_fill_order():
        total += len(s.cards)
    return total
