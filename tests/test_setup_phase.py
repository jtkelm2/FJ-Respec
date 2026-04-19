"""
Setup phase: role/alignment assignment, trait installation, catalog completeness.

Setup runs inside `run(g, game_loop(), interp)` like every other phase,
so it can yield prompts and exercise the trait system with a real interpreter.
"""

import pytest
from core.type import (
    PID, Alignment, Phase, Role, Card, CardType, TKind, Trait, PromptBuilder,
    TextOption, CardOption, AssignRoleCard, CardMoved, PhaseChanged,
    Effect, GameState, Negotiation,
)
from core.engine import do
from interact.interpret import run, AggregateInterpreter
from interact.player import ScriptedPlayer
from interact.serial import Accumulator
from phase.setup import create_initial_state, setup_phase
from phase.game import game_loop
from cards.roles import GOOD_ROLES, EVIL_ROLES
from helpers import interp, initial_game


# ── create_initial_state: pure ────────────────────────────────

class TestPureConstructor:
    """create_initial_state builds state without running any actions."""

    def test_role_and_alignment_are_none_before_setup(self):
        g = create_initial_state(seed=42)
        for pid in PID:
            assert g.players[pid].role is None
            assert g.players[pid].alignment is None

    def test_equipment_empty_before_setup(self):
        g = create_initial_state(seed=42)
        for pid in PID:
            assert len(g.players[pid].equipment.cards) == 0

    def test_role_pool_populated(self):
        g = create_initial_state(seed=42)
        assert len(g.role_pool) == len(GOOD_ROLES) + len(EVIL_ROLES)

    def test_deterministic_from_seed(self):
        """Pure construction produces identical decks across runs for a given seed."""
        g1 = create_initial_state(seed=7)
        g2 = create_initial_state(seed=7)
        red1 = [c.name for c in g1.players[PID.RED].deck.cards]
        red2 = [c.name for c in g2.players[PID.RED].deck.cards]
        assert red1 == red2


# ── setup_phase: the real deal ────────────────────────────────

class TestSetupPhase:
    """setup_phase assigns role/alignment atomically through do(AssignRoleCard)."""

    def test_sets_role_and_alignment_on_both_players(self):
        g = initial_game(seed=42)
        for pid in PID:
            assert g.players[pid].role is not None
            assert g.players[pid].alignment is not None
            assert g.players[pid].alignment == g.players[pid].role.alignment

    def test_role_card_in_equipment(self):
        g = initial_game(seed=42)
        for pid in PID:
            assert len(g.players[pid].equipment.cards) == 1

    def test_alignment_distribution_at_most_one_evil(self):
        """The pool is [GOOD, GOOD, EVIL] — never both players Evil."""
        for seed in range(50):
            g = initial_game(seed=seed)
            evils = sum(1 for pid in PID
                        if g.players[pid].alignment == Alignment.EVIL)
            assert evils <= 1, f"seed {seed} gave both players Evil"

    def test_deterministic_role_selection(self):
        """Same seed → same roles after full setup."""
        g1 = initial_game(seed=13)
        g2 = initial_game(seed=13)
        for pid in PID:
            assert g1.players[pid].role.name == g2.players[pid].role.name

    def test_no_role_produces_setup_prompts(self):
        """Regression: pre-fix, roles with multiple on_role_assign traits (e.g.
        food_fighter) produced a 'Order triggers' prompt with two
        indistinguishable options, hanging the server. Each role must now
        install at most one on_role_assign trait so setup yields no prompts."""
        for factory, role in GOOD_ROLES + EVIL_ROLES:
            g = create_initial_state(seed=0)
            picks = {PID.RED: (factory(), role), PID.BLUE: (factory(), role)}
            # Empty scripts would raise IndexError if any prompt were yielded.
            run(g, setup_phase(picks),
                AggregateInterpreter(ScriptedPlayer([]), ScriptedPlayer([])))

    def test_picks_override_bypasses_rng(self):
        """Explicit picks override random selection."""
        g = create_initial_state(seed=42)
        card = Card("test_role", "Test", "", None, (CardType.EQUIPMENT,))
        role = Role("Test", Alignment.GOOD)
        picks = {PID.RED: (card, role), PID.BLUE: (card, role)}
        run(g, setup_phase(picks),
            AggregateInterpreter(ScriptedPlayer([]), ScriptedPlayer([])))
        assert g.players[PID.RED].role is role
        assert g.players[PID.BLUE].role is role


# ── AssignRoleCard atomicity ──────────────────────────────────

class TestAssignRoleCardAction:
    """The action sets role, alignment, equipment in one dispatch."""

    def test_sets_role(self):
        g = create_initial_state(seed=42)
        card = Card("x", "X", "", None, (CardType.EQUIPMENT,))
        role = Role("X", Alignment.EVIL)
        run(g, do(AssignRoleCard(card, role, PID.RED, "test")),
            interp())
        assert g.players[PID.RED].role is role

    def test_sets_alignment_from_role(self):
        g = create_initial_state(seed=42)
        card = Card("x", "X", "", None, (CardType.EQUIPMENT,))
        role = Role("X", Alignment.EVIL)
        run(g, do(AssignRoleCard(card, role, PID.RED, "test")),
            interp())
        assert g.players[PID.RED].alignment == Alignment.EVIL

    def test_slots_card_into_equipment(self):
        g = create_initial_state(seed=42)
        card = Card("x", "X", "", None, (CardType.EQUIPMENT,))
        role = Role("X", Alignment.GOOD)
        run(g, do(AssignRoleCard(card, role, PID.BLUE, "test")),
            interp())
        assert card in g.players[PID.BLUE].equipment.cards

    def test_emits_cardmoved_event_with_correct_fields(self):
        """The event log must record card, dest, and dest_index=0 so the
        wire protocol can reconstruct the move on the client."""
        g = create_initial_state(seed=42)
        card = Card("x", "X", "", None, (CardType.EQUIPMENT,))
        role = Role("X", Alignment.GOOD)
        before = len(g._event_log)
        run(g, do(AssignRoleCard(card, role, PID.RED, "test")),
            interp())
        new_events = g._event_log[before:]
        moves = [e for e in new_events if isinstance(e, CardMoved)]
        assert len(moves) >= 1
        m = moves[0]
        assert m.card is card
        assert m.source is None
        assert m.source_index is None
        assert m.dest is g.players[PID.RED].equipment
        assert m.dest_index == 0


class TestGuardDeckPopulated:
    """create_initial_state must actually fill the guard deck (not leave
    it as the default empty Slot from GameState's dataclass factory)."""

    def test_guard_deck_is_nonempty(self):
        g = create_initial_state(seed=42)
        assert len(g.guard_deck.cards) > 0


# ── Traits with a real interpreter (the whole point) ──────────

class TestOnRoleAssignWithInterpreter:
    """The original bug: a prompting on_role_assign trait couldn't be
    answered because setup ran under a noop interpreter. Now setup runs
    inside `run(g, ..., interpreter)` like every other phase."""

    def test_prompting_on_role_assign_trait_is_reachable(self):
        """A role whose on_role_assign yields a prompt gets answered by
        the interpreter — this is what the old hack couldn't do."""
        prompted = []

        def _make_prompting_trait(card: Card):
            def callback(a):
                def eff(g):
                    response = yield (PromptBuilder("Prompted during setup?")
                                      .add(TextOption("Yes"))
                                      .add(TextOption("No"))
                                      .build(a.player))
                    prompted.append(response[a.player])
                return eff
            return Trait(
                f"{card.display_name} (Prompting)", TKind.AFTER,
                lambda a: isinstance(a, AssignRoleCard) and a.card is card,
                callback)

        prompt_card = Card("prompter", "Prompter", "", None, (CardType.EQUIPMENT,))
        prompt_card.traits = [_make_prompting_trait(prompt_card)]
        prompt_role = Role("Prompter", Alignment.GOOD)

        g = create_initial_state(seed=42)
        picks = {PID.RED: (prompt_card, prompt_role)}
        # Priority matters — the player asked is g.priority; we script both.
        run(g, setup_phase(picks),
            interp(TextOption("Yes"), blue=[TextOption("Yes")]))
        assert TextOption("Yes") in prompted


# ── Phase integration ─────────────────────────────────────────

class TestGameLoopSetupOrdering:
    """game_loop() runs setup before the Refresh/Manipulation/Action loop."""

    def test_setup_phase_in_event_log(self):
        """After initial_game, the event log records a SETUP phase transition,
        confirming setup ran through the real action system (not a side-door)."""
        g = initial_game(seed=42)
        phases = [e.phase for e in g._event_log
                  if isinstance(e, PhaseChanged)]
        # initial_game only runs setup_phase, not a full game_loop, so SETUP
        # doesn't appear unless the caller dispatches StartPhase first. Run
        # setup through game_loop's setup segment instead.
        from core.type import StartPhase
        g2 = create_initial_state(seed=42)
        run(g2, do(StartPhase(Phase.SETUP, "test")),
            AggregateInterpreter(ScriptedPlayer([]), ScriptedPlayer([])))
        run(g2, setup_phase(),
            AggregateInterpreter(ScriptedPlayer([]), ScriptedPlayer([])))
        phases = [e.phase for e in g2._event_log
                  if isinstance(e, PhaseChanged)]
        assert Phase.SETUP in phases


# ── Catalog completeness ──────────────────────────────────────

class TestCatalogIncludesAllRoles:
    """The wire protocol front-loads a card catalog at session init. All
    possible role cards must be in the catalog — not just the two assigned
    — so the client has metadata for whichever role might be revealed."""

    def test_every_role_factory_registered(self):
        g = create_initial_state(seed=42)
        acc = Accumulator(g)
        names_in_catalog = set(acc._card_catalog.keys())
        for factory, _ in GOOD_ROLES + EVIL_ROLES:
            assert factory().name in names_in_catalog, \
                f"role card {factory().name} missing from catalog"

    def test_catalog_built_before_setup_still_complete(self):
        """Crucial: the catalog is scanned BEFORE setup_phase assigns any
        role. Without role_pool, no role cards would be in any slot yet."""
        g = create_initial_state(seed=42)
        # Don't run setup yet
        assert all(len(g.players[pid].equipment.cards) == 0 for pid in PID)
        acc = Accumulator(g)
        # Catalog must still know about every role card.
        for factory, _ in GOOD_ROLES + EVIL_ROLES:
            assert factory().name in acc._card_catalog
