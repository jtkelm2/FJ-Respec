from core.type import *
from core.engine import do, simultaneously


def manipulation_phase() -> Effect:
    """
    Manipulation Phase (fully async of either player):
      Each player independently:
        1. Chooses: Manipulate or Dump
        2. Executes that choice (swap loop + force, or discard/refresh hand)
        3. Post-manipulation: mix third card, shuffle, deal one to opponent, clean up
    """
    def player_effect(pid) -> Effect:
        def eff(g):
            forcing: dict = {'card': None}
            pb = (PromptBuilder("Choose: Manipulate or Dump?")  # pragma: no mutate
                  .add(TextOption("Manipulate"))  # pragma: no mutate
                  .add(TextOption("Dump")))  # pragma: no mutate
            response = yield pb.build(pid)  # pragma: no mutate
            if response[pid] == TextOption("Manipulate"):  # pragma: no mutate
                yield from _manipulate(pid, forcing)(g)  # pragma: no mutate
            else:
                yield from _dump(pid)(g)  # pragma: no mutate
            yield from _post_manipulation(pid, forcing['card'])(g)
        return eff

    return simultaneously({pid: player_effect(pid) for pid in PID})


# --- Helpers ---

def _manipulate(pid: PID, forcing: dict) -> Effect:
    """Swap cards between manipulation field and hand; optionally force.

    On force, also pick which of the two manipulation-field cards to send.
    The selection is captured before the third card is drawn, so the
    manipulator never sees the third card."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]

        # Swap loop
        while True:
            mf_cards = p.sidebar.cards
            hand_cards = p.hand.cards

            pb = PromptBuilder("Choose a card from manipulation field to swap, or Done:")  # pragma: no mutate
            pb.add_cards(list(mf_cards))  # pragma: no mutate
            pb.add(TextOption("Done"))  # pragma: no mutate
            response = yield pb.build(pid)  # pragma: no mutate

            match response[pid]:
                case TextOption("Done"):
                    break
                case CardOption(mf_card):
                    hpb = PromptBuilder("Choose a card from hand to swap with:")  # pragma: no mutate
                    hpb.add_cards(list(hand_cards))  # pragma: no mutate
                    hpb.context(CardOption(mf_card))  # pragma: no mutate
                    response = yield hpb.build(pid)  # pragma: no mutate
                    chosen = response[pid]
                    assert isinstance(chosen, CardOption)
                    hand_card = chosen.card

                    # Swap: each card takes the other's index
                    s_idx = p.sidebar.cards.index(mf_card)
                    h_idx = p.hand.cards.index(hand_card)
                    yield from do(Slot2Slot(p.sidebar, p.hand, "manipulation swap", s_idx, h_idx))(g)  # pragma: no mutate
                    h_idx_now = p.hand.cards.index(hand_card)
                    yield from do(Slot2Slot(p.hand, p.sidebar, "manipulation swap", h_idx_now, s_idx))(g)  # pragma: no mutate

        # Force option: discard equipment to choose which card to send
        equipment_cards = p.equipment.cards
        if equipment_cards:
            pb = PromptBuilder("Force? (Discard equipment to choose which card to send)")  # pragma: no mutate
            pb.add(TextOption("Don't force"))  # pragma: no mutate
            pb.add_cards(list(equipment_cards))  # pragma: no mutate
            response = yield pb.build(pid)  # pragma: no mutate
            match response[pid]:
              case CardOption(equip):
                pass
              case _:
                equip = None
            if equip is not None:
                yield from do(Discard(pid, equip, "forcing"))(g)  # pragma: no mutate
                cpb = PromptBuilder("Choose which manipulation card to send to opponent:")  # pragma: no mutate
                cpb.add_cards(list(p.sidebar.cards))  # pragma: no mutate
                response = yield cpb.build(pid)  # pragma: no mutate
                chosen = response[pid]
                assert isinstance(chosen, CardOption)
                forcing['card'] = chosen.card

    return effect


def _dump(pid: PID) -> Effect:
    """Discard or refresh each card in hand. Elusive cards must be refreshed."""
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        other_pid = other(pid)

        for card in list(p.hand.cards):
            if card.is_elusive:
                yield from do(Refresh(card, other_pid, "dump elusive"))(g)  # pragma: no mutate
            else:
                pb = (PromptBuilder(f"{card.display_name}:")  # pragma: no mutate
                      .add(TextOption("Discard"))  # pragma: no mutate
                      .add(TextOption("Refresh"))  # pragma: no mutate
                      .context(CardOption(card)))  # pragma: no mutate
                response = yield pb.build(pid)  # pragma: no mutate
                if response[pid] == TextOption("Discard"):  # pragma: no mutate
                    yield from do(Discard(other_pid, card, "dump discard"))(g)  # pragma: no mutate
                else:
                    yield from do(Refresh(card, other_pid, "dump refresh"))(g)  # pragma: no mutate

    return effect


def _post_manipulation(pid: PID, forced_card: Card | None) -> Effect:
    """
    Post-manipulation steps:
      1. PostManipulate primitive: introduce third card from opponent's deck,
         randomly (or by forcing) place one card on opponent's deck-top, the
         remaining two on opponent's refresh. The manipulator never sees the
         third card.
      2. Fill each open opponent action slot by drawing from opponent's deck.
         (The first such draw will yield the rigged/forced card.)
      3. Refresh any elusive cards still in hand.
    """
    def effect(g: GameState) -> Negotiation:
        p = g.players[pid]
        other_pid = other(pid)
        other_p = g.players[other_pid]

        # Step 1: atomic third-card mix + distribution
        yield from do(EnsureDeck(other_pid, "manipulation deal"))(g)  # pragma: no mutate
        yield from do(PostManipulate(pid, forced_card, "post manipulation"))(g)  # pragma: no mutate

        # Step 2: fill each open opponent action slot from opponent's deck
        open_slots = [s for s in other_p.action_field.slots_in_fill_order() if s.is_empty()]
        for slot in open_slots:
            yield from do(EnsureDeck(other_pid, "deal to action field"))(g)  # pragma: no mutate
            yield from do(Slot2Slot(other_p.deck, slot, "deal to action field"))(g)  # pragma: no mutate

        # Step 3: refresh any elusive cards still in hand (back to other's refresh pile)
        for card in list(p.hand.cards):
            if card.is_elusive:
                yield from do(Refresh(card, other_pid, "refresh elusive from hand"))(g)  # pragma: no mutate

    return effect
