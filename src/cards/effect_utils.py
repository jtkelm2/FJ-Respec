from core.type import PID, Action, AddToKillstack, Card, Discard, GameState


def _kill_slayer(a: Action) -> PID:
    """Extract the slayer PID from a kill action (AddToKillstack or Discard)."""
    match a:
        case AddToKillstack(_, slayer, _, _): return slayer
        case Discard(discarder, _, _): return discarder
    raise ValueError(f"Not a kill action: {a}")  # pragma: no mutate

def _const(val):
    """Modifier callback that ignores the query/base and returns a constant."""
    def cb(_q, _v):
        def eff(_g):
            return val; yield  # pragma: no cover
        return eff
    return cb

def _equipped_by(g:GameState, card:Card) -> PID | None:
    for player in PID:
        if card.slot is g.players[player].equipment: return player
    return None