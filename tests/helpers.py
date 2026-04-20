"""Shared test utilities for the Fool's Journey test suite."""

import random
from core.type import (
    GameState, PlayerState, PID, Slot, SlotKind,
)
from core.engine import do
from interact.interpret import run, AggregateInterpreter
from interact.player import ScriptedPlayer
from phase.setup import create_initial_state, setup_phase


def interp(*red_choices, blue=None):
    """Build an interpreter from scripted choice lists."""
    if blue is None:
        blue = []
    return AggregateInterpreter(
        ScriptedPlayer(list(red_choices)),
        ScriptedPlayer(list(blue)),
    )


def minimal_game(seed=42):
    """Lightweight GameState with empty slots (no full decks)."""
    return GameState(
        rng=random.Random(seed),
        priority=PID.RED,
        players={PID.RED: PlayerState("red"), PID.BLUE: PlayerState("blue")},
        guard_deck=Slot("guard_deck", SlotKind.GUARD_DECK),
    )


def initial_game(seed=42, picks=None):
    """Post-setup GameState: shuffled decks and roles assigned. For tests that
    want a realistic starting state. `picks` overrides random role selection."""
    g = create_initial_state(seed=seed)
    run(g, setup_phase(picks), AggregateInterpreter(ScriptedPlayer([]), ScriptedPlayer([])))
    return g


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
    return total
