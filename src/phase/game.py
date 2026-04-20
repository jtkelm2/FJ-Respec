from core.type import *
from core.engine import do
from phase.setup import setup_phase
from phase.refresh import refresh_phase
from phase.manipulation import manipulation_phase
from phase.action import action_phase


def game_loop() -> Effect:
    """Full game from setup to game over. Setup → (Refresh → Manipulation → Action)*."""
    def effect(g: GameState) -> Negotiation:
        yield from do(StartPhase(Phase.SETUP, "game loop"))(g)  # pragma: no mutate
        yield from setup_phase()(g)
        yield from _settle(g)
        if g.is_over: return

        yield from _play_phases()(g)
    return effect


def _play_phases() -> Effect:
    """Repeating Refresh → Manipulation → Action until game-over. Assumes setup done.

    Exposed so tests that craft a post-setup state by hand can drive the
    active-phase loop without going through setup_phase."""
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

    pb_not_yet = (PromptBuilder("Announce that you have killed The World?").yesno())  # pragma: no mutate
    pb_already = (PromptBuilder("You have already announced that you have killed The World.").notify())
    
    for player in PID:
        if not g.players[player].claims_world_killed:
            response = yield pb_not_yet.build(player)
            g.players[player].claims_world_killed = response[player] == TextOption("Yes")
        else:
            yield pb_already.build(player)