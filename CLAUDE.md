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
