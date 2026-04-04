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

## Testing

### New features must be validated

Every new feature, action, or phase must be accompanied by tests that pass both the test suite and mutation testing. The workflow:

1. Write tests with strong oracles (specific value assertions, not just "didn't crash").
2. Run `python -m pytest tests/`.
3. Run `mutmut run`, then `mutmut results` and `mutmut show <name>` to inspect survivors.
4. Any surviving mutant that changes *control flow* or *arithmetic* in the new code represents a real test gap. Write a targeted test to kill it, then rerun.

The goal is not 100% mutation score — it's that every *behavioral* mutant in the new code is killed.

### What makes a test worth writing

Test quality is not measured by line coverage. Line coverage tells you code was *executed*, not that its *results were checked*. The meaningful hierarchy, backed by empirical research (Just et al. 2014, Inozemtseva & Holmes 2014), is:

1. **Mutation score** — can the test detect small injected faults? Strongest predictor of real fault-detection ability.
2. **Assertion density / oracle strength** — `assert hp == 5` catches faults; `assert result is not None` catches almost nothing.
3. **Property/invariant coverage** — "total card count is conserved across any operation" catches classes of bugs, not single instances.
4. **Suite size** — more tests helps, but only with strong oracles.
5. **Line/branch coverage** — necessary but nearly useless alone. Creates false confidence when assertions are weak.

### Testing patterns

- **Boundary value analysis** via `@pytest.mark.parametrize` — test at every edge of a value range (0, 1, N-1, N, N+1, extreme).
- **Metamorphic relations** — verify the *shape* of a function (e.g. "increasing sharpness never increases damage") without hardcoding expected values.
- **Conservation invariants** — `count_all_cards()` in `tests/helpers.py` verifies total card count before and after any phase. Cards must never be created or destroyed.
- **Negative tests** — `pytest.raises(AssertionError)` for contract violations (empty draws, bad prompts in `simultaneously()`).
- **Scripted interpreters** — `interp(0, 1, blue=[0])` from `tests/helpers.py` provides deterministic player choices. When testing `simultaneously()`, RED is answered first (dict insertion order), and each player's prompts interleave accordingly.

### Mutation testing with mutmut

Configured in `setup.cfg`. Commands:

```
mutmut run                     # full run
mutmut results                 # list survivors
mutmut show <mutant_name>      # inspect a specific mutant's diff
```

`mutmut results` only shows *surviving* and *no-tests* mutants. Killed mutants are silent. A surviving mutant means the test suite cannot distinguish the mutated code from the original.

**Interpreting survivors:**

- Mutations to `source: str` fields on Actions, card factory display strings, `CLIInterpreter`, and `_fire_triggers`/trait dispatch (dead until traits land) are equivalent mutants — not real test gaps. These lines are marked `# pragma: no mutate` so mutmut skips them.
- Mutations that change *control flow* or *arithmetic* are genuine. Examples: `not p.is_dead` → `p.is_dead`, `and` → `or` in assertions, `[:-1]` → `[:-2]` in slicing.
- Use `mutmut tests-for-mutant <name>` to see which tests mutmut runs against a specific mutant. If the test you expect to kill it isn't listed, the test may not exist, or coverage-based test selection may have mapped the function incorrectly.

**Whitelisting lines from mutation:**

Lines that produce only equivalent mutants (debug strings, dead code, display-only values) are marked with `# pragma: no mutate`. This is the only pragma syntax supported by mutmut 3.5 — it works per-line only, not per-block or per-region. When adding new code that has equivalent-mutant-prone lines (source strings on Actions, prompt display text, factory string fields), add the pragma. When the trait system lands, remove the pragmas from `_fire_triggers`, `_get_triggers`, `_player_to_choose_replacement`, and the trait dispatch branch in `do()`.
