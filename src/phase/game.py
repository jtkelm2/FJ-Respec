from core.type import *
from core.engine import do
from phase.refresh import refresh_phase
from phase.manipulation import manipulation_phase
from phase.action import action_phase


def game_loop() -> Effect:
    """
    Main game loop: Refresh → Manipulation → Action, repeating until
    a win condition is met or both players are lost to exhaustion.
    """
    def effect(g: GameState) -> Negotiation:
        while not g.is_over:
            yield from do(StartPhase(Phase.REFRESH, "game loop"))(g)  # pragma: no mutate
            yield from refresh_phase()(g)
            yield from _settle(g)
            if g.is_over: return

            yield from do(StartPhase(Phase.MANIPULATION, "game loop"))(g)  # pragma: no mutate
            yield from manipulation_phase()(g)
            yield from _settle(g)
            if g.is_over: return

            yield from do(StartPhase(Phase.ACTION, "game loop"))(g)  # pragma: no mutate
            yield from action_phase()(g)
            yield from _settle(g)
            if g.is_over: return
            yield from _offer_world_claims(g)
            yield from _settle(g)
            if g.is_over: return

    return effect


def _settle(g: GameState) -> Negotiation:
    """Check game state and dispatch GameOver if warranted."""
    result = g.check_game_over()
    if result is not None:
        yield from do(GameOver(result, "game over"))(g)  # pragma: no mutate


def _offer_world_claims(g: GameState) -> Negotiation:
    """At end of action phase, ask each player who hasn't yet claimed
    whether they wish to announce that they have killed The World."""

    pb = (PromptBuilder("Announce that you have killed The World?")  # pragma: no mutate
          .add(TextOption("No"))   # pragma: no mutate
          .add(TextOption("Yes")))  # pragma: no mutate

    if not any(g.players[player].claims_world_killed for player in PID):
        response = yield PromptBuilder.both(pb)
        for player in PID:
            if response[player] == TextOption("Yes"):
                g.players[player].claims_world_killed = True
        return

    for player in PID:
        if not g.players[player].claims_world_killed:
            response = yield pb.build(player)
            if response[player] == TextOption("Yes"):
                g.players[player].claims_world_killed = True
            return