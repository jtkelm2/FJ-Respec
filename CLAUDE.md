# Fool's Journey — Executable Spec

A 2-player card game engine in pure Python (stdlib only). Generator-based effect system with hookable actions via a trait system (before/replacement/after).

## Imperatives

### All mutations go through `do(Action)`

Every game state mutation must be expressed as an Action dispatched via `do()`. No direct field writes, no `slot.slot()` calls outside of `_apply_action`. If the Action you need doesn't exist, create it in `type.py` and define its semantics in `_apply_action` in `engine.py`. This is non-negotiable: the trait system can only intercept what flows through `do()`.

### No card-specific logic in phases or engine

Phase implementations (`phase/`) express general game rules only. Card-specific behavior (e.g. "Skeleton draws underneath on placement", "Cardsharp rearranges action field") belongs in the trait system, not in hardcoded branches. The architecture must be extensible enough to accommodate a data-centric approach to custom card logic.

### Actions are compositional

Primitive atoms (`SlotCard`, `Slot2Slot`, `Slot2SlotAll`, `Shuffle`) are the mechanical building blocks. Higher-level actions (`Draw`, `Discard`, `ShuffleRefreshIntoDeck`) compose from them via `do()` inside `_apply_action`. Every layer is hookable.

### This is a headless game engine

This project is the authoritative game logic layer. It must remain frontend-agnostic. Known consumers:

- Interactive CLI debugging sessions
- Godot multiplayer adaptation (agnostic to local human / remote human / AI / script play)
- Replay and game analysis tool
- Potential: tournament server, automated balancing/playtesting harness, rule-variant sandbox

The `Interpreter` abstraction is the boundary between engine and frontend. Before making changes, consider whether they compromise any of these use cases.

## Architecture

- `core/type.py` — All data structures, actions, traits
- `core/engine.py` — `run()`, `do()`, `_apply_action()`, trait dispatch
- `core/interpret.py` — Interpreter abstraction (CLI, Scripted, Aggregate)
- `cards.py` — Card factory functions
- `combat.py` — Weapon selection and combat resolution
- `phase/` — Game phase implementations (setup, refresh, ...)

## Running tests

```
python -m pytest tests/
```

## Testing methodology

### What makes a test worth writing

Test quality is not measured by line coverage. Line coverage tells you code was *executed*, not that its *results were checked*. The meaningful hierarchy, backed by empirical research (Just et al. 2014, Inozemtseva & Holmes 2014), is:

1. **Mutation score** — can the test detect small injected faults? This is the strongest predictor of real fault-detection ability.
2. **Assertion density / oracle strength** — does the test check a specific value, or just that nothing crashed? `assert hp == 5` catches faults; `assert result is not None` catches almost nothing.
3. **Property/invariant coverage** — are there tests that verify things like "total card count is conserved" across any operation? These catch classes of bugs, not single instances.
4. **Suite size** — more tests is better, but only if they have strong oracles.
5. **Line/branch coverage** — necessary but nearly useless alone. High coverage with weak assertions is worse than moderate coverage with strong assertions, because it creates false confidence.

### How this test suite is organized

Tests live in `tests/`. Shared helpers are in `tests/helpers.py`; path setup is in `tests/conftest.py`.

| File | What it tests |
|---|---|
| `test_slot_mechanics.py` | Slot bookkeeping, LIFO ordering, card conservation, `Card.is_type()` |
| `test_hp_system.py` | Parametrized damage/heal boundaries, floor/ceiling clamping, multi-step HP composition |
| `test_actions.py` | Action primitives through `do()`: Draw, EnsureDeck, SlotCard, Slot2Slot, FlipPriority, Refresh, Discard |
| `test_combat.py` | Fists/weapon combat, sharpness-damage monotonicity (metamorphic property), `can_use_weapon` boundaries |
| `test_manipulation.py` | `_dump`, `_manipulate`, `_post_manipulation` helpers directly, plus full `manipulation_phase()` integration |
| `test_simultaneously.py` | The async effect combinator: interleaving, early finish, contract violation rejection |
| `test_invariants.py` | Cross-cutting properties: card conservation across phases, dead-player skip during refresh |
| `test_engine.py` | Original tests (HP, discard, combat, refresh basics) |

**Key patterns used:**

- **Boundary value analysis** via `@pytest.mark.parametrize` — damage amounts at 0, 1, 19, 20, 21, 999 hit every edge of the HP pipeline.
- **Metamorphic relations** — `TestDamageMonotonicity` verifies that increasing sharpness never increases damage, for any fixed enemy level. This tests the *shape* of the combat formula without hardcoding expected values.
- **Conservation invariants** — `count_all_cards()` verifies total card count is identical before and after any phase. Cards must never be created or destroyed by slot operations.
- **Negative tests** — `pytest.raises(AssertionError)` for drawing from empty slots, deslotting absent cards, and violating the `simultaneously()` contract.
- **Scripted interpreters** — `interp(0, 1, blue=[0])` provides deterministic player choices. When testing manipulation or simultaneously, trace the prompt sequence carefully: `simultaneously()` answers RED first (dict insertion order), and each player's dump/manipulate prompts interleave accordingly.

### Mutation testing with mutmut

Configured in `setup.cfg`. Run with:

```
mutmut run                     # full run (~2 min)
mutmut results                 # list survivors
mutmut show <mutant_name>      # inspect a specific mutant's diff
```

**How to read the results:**

`mutmut results` only shows *surviving* and *no-tests* mutants. Killed mutants (the good ones) are silent. A surviving mutant means the test suite cannot distinguish the mutated code from the original — either the mutation is in untested behavior, or the tests have weak oracles for that code path.

**Expected noise in this codebase:**

Most survivors are equivalent mutants that don't represent real test gaps:

- **`source: str` parameter mutations (~250)** — every Action has a `source` field for debugging provenance. Mutating `"refresh"` to `None` doesn't change game behavior. No test should check these strings.
- **`_fire_triggers` / trait dispatch in `do()` (~50)** — dead code until the trait system is implemented. `_get_triggers()` returns `[]`, so these paths never execute.
- **`CLIInterpreter` (16 no-tests)** — interactive I/O, untestable in automation.
- **Card factory string fields** — mutating display names or card names doesn't affect game logic.

**When a surviving mutant is genuinely interesting:**

Look for mutations that change *control flow* or *arithmetic* rather than strings. Examples that led to real test additions:

- `not p.is_dead` → `p.is_dead` in `_deal_hand` — revealed that no test exercised the dead-player guard during refresh.
- `and` → `or` in `simultaneously()`'s `_extract` assertion — revealed that no test sent a malformed prompt to test the contract.
- `[:-1]` → `[:-2]` in `_deal_action_cards` — should have been killed by existing tests; survival indicated a mutmut test-selection issue, not a real gap.

**Iterating on mutation score:**

The workflow is: run mutmut, scan survivors for behavioral mutations (skip `source`-string and dead-code noise), write a targeted test for each real gap, rerun. The goal is not 100% mutation score — it's that every *behavioral* mutant is killed.
