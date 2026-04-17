from core.type import *


def do(action: Action) -> Effect:
    def effect(g: GameState) -> Negotiation:
        # Instead-of: find an applicable replacement and delegate to it.
        candidates = [ tr for tr in _get_triggers(g, action) if tr.kind == TKind.REPLACEMENT ]
        if candidates:
          if len(candidates) == 1:
            chosen = candidates[0]
          else:
            pid = _player_to_choose_replacement(g, action)
            pb = PromptBuilder(f"Choose replacement for {action}:")  # pragma: no mutate
            for tr in candidates:
                pb.add(TextOption(tr.name))
            response = yield pb.build(pid)
            match response[pid]:
              case TextOption(name):
                chosen = next(tr for tr in candidates if tr.name == name)
              case _: raise ValueError(f"Unexpected response: {response[pid]}")  # pragma: no mutate
          yield from chosen.callback(action)(g)
          return

        # Before triggers
        yield from _fire_triggers(g, action, TKind.BEFORE)

        # Execute
        yield from _apply_action(action)(g)

        # After triggers
        yield from _fire_triggers(g, action, TKind.AFTER)
    return effect

def simultaneously(effects: dict[PID, Effect]) -> Effect:
    """Combinator for asynchronously combining Effects, via AskEither.

    Each effect must only yield single-player Ask prompts for its own PID.
    Pending prompts from both players are merged into one AskEither;
    whichever player the interpreter answers for has their generator advanced.
    """
    def effect(g: GameState) -> Negotiation:
        gens = {pid: eff(g) for pid, eff in effects.items()}
        pending: dict[PID, PromptHalf] = {}

        def _extract(prompt:Prompt, pid:PID):
            assert prompt.kind == PKind.EITHER and len(prompt.for_player) == 1
            return prompt.for_player[pid]

        for pid in PID:
            try: pending[pid] = _extract(next(gens[pid]), pid)
            except StopIteration: pass

        while pending:
            response = yield AskEither(pending)
            answered_pid = next(iter(response))
            del pending[answered_pid]
            try: pending[answered_pid] = _extract(gens[answered_pid].send(response), answered_pid)
            except StopIteration: pass

    return effect


################## Helpers #########

def _apply_action(action: Action) -> Effect:
    def effect(g:GameState) -> Negotiation:
        match action:
            case Death(target):
                p = g.players[target]
                p.is_dead = True
                g._event_log.append(PlayerDied(target))
            case Refresh(card, player, source):
                yield from do(SlotCard(card, g.players[player].refresh, "refresh"))(g)  # pragma: no mutate
            case Discard(discarder, card, source):
                yield from do(SlotCard(card, g.players[discarder].discard, "discard"))(g)  # pragma: no mutate
            case Slay(slayer, enemy, ws, source):
                if ws is None:
                   yield from do(Discard(slayer, enemy, "combat (fists)"))(g)  # pragma: no mutate
                   return
                yield from do(SlotCard(enemy, ws.killstack, "slay"))(g)  # pragma: no mutate
            case SetHP(target, value, source):
                p = g.players[target]
                old_hp = p.hp
                new_hp = value
                if p.hp_floor is not None:
                    new_hp = max(new_hp, p.hp_floor)
                if p.hp_ceiling is not None:
                    new_hp = min(new_hp, p.hp_ceiling)
                p.hp = new_hp
                g._event_log.append(HPChanged(target, old_hp, p.hp))
                if p.hp <= 0:
                    yield from do(Death(target))(g)
            case SlotCard(card, dest, source):
                orig = card.slot
                assert orig is not None
                src_idx = orig.cards.index(card)
                yield from do(Slot2Slot(orig, dest, source, src_idx))(g)
            case Slot2Slot(orig, dest, source, source_index, dest_index):
                if orig.is_empty(): return
                card = orig.draw(at=source_index)
                dest.slot(card, at=dest_index)
                g._event_log.append(CardMoved(card, orig, source_index, dest, dest_index))
            case Slot2SlotAll(orig, dest, source):
                count = len(orig.cards)
                cards = list(orig.cards)
                dest.slot(*cards)
                if count > 0:
                    g._event_log.append(SlotTransferred(orig, dest, count))
            case Heal(target, amount, source):
                yield from do(SetHP(target, g.players[target].hp + amount, source))(g)  # pragma: no mutate
            case Damage(target, amount, source):
                yield from do(SetHP(target, g.players[target].hp - amount, source))(g)  # pragma: no mutate
            case Shuffle(slot, source):
                g.shuffle(slot)
                g._event_log.append(SlotShuffled(slot))
            case ShuffleRefreshIntoDeck(player, source):
                p = g.players[player]
                yield from do(Slot2SlotAll(p.refresh, p.deck, "shuffle refresh"))(g)  # pragma: no mutate
                yield from do(Shuffle(p.deck, "shuffle refresh"))(g)  # pragma: no mutate
            case EnsureDeck(player, source):
                p = g.players[player]
                if p.deck.is_empty():
                    yield from do(ShuffleRefreshIntoDeck(player, "exhaustion recovery"))(g)  # pragma: no mutate
                if p.deck.is_empty():
                    for pid in PID:
                        yield from do(Death(pid, source="exhaustion"))(g)  # pragma: no mutate
            case Draw(player):
                yield from do(EnsureDeck(other(player),"draw to hand"))(g)  # pragma: no mutate
                yield from do(Slot2Slot(g.players[other(player)].deck, g.players[player].hand, "draw"))(g)  # pragma: no mutate
            case Equip(player, card, source):
                p = g.players[player]
                while len(p.equipment.cards) >= p.max_equipment:
                    pb = PromptBuilder("Equipment full. Discard which?")  # pragma: no mutate
                    pb.add_cards(list(p.equipment.cards))  # pragma: no mutate
                    pb.context(CardOption(card))  # pragma: no mutate
                    response = yield pb.build(player)  # pragma: no mutate
                    chosen = response[player]
                    assert isinstance(chosen, CardOption)
                    to_discard = chosen.card
                    yield from do(Discard(player, to_discard, "equip overflow"))(g)  # pragma: no mutate
                yield from do(SlotCard(card, p.equipment, "equip"))(g)  # pragma: no mutate
            case Wield(player, card, source):
                p = g.players[player]
                if len(p.weapon_slots) == 1:
                    ws = p.weapon_slots[0]
                else:
                    pb = PromptBuilder("Wield in which weapon slot?")  # pragma: no mutate
                    for ws in p.weapon_slots:
                        pb.add(WeaponSlotOption(ws))  # pragma: no mutate
                    pb.context(CardOption(card))  # pragma: no mutate
                    response = yield pb.build(player)  # pragma: no mutate
                    chosen = response[player]
                    assert isinstance(chosen, WeaponSlotOption)
                    ws = chosen.weapon_slot
                if ws.weapon is not None:
                    yield from do(Discard(player, ws.weapon, "wield old weapon"))(g)  # pragma: no mutate
                for kill_card in list(ws.killstack.cards):
                    yield from do(Discard(player, kill_card, "wield kill pile"))(g)  # pragma: no mutate
                old_slot = card.slot
                src_idx = old_slot.cards.index(card) if old_slot is not None else None
                ws.wield(card)
                g._event_log.append(CardMoved(card, old_slot, src_idx, ws._weapon_slot, 0))
            case Disarm(player, source):
                p = g.players[player]
                for ws in p.weapon_slots:
                    if ws.weapon is not None:
                        yield from do(Discard(player, ws.weapon, "disarm weapon"))(g)  # pragma: no mutate
                    for kill_card in list(ws.killstack.cards):
                        yield from do(Discard(player, kill_card, "disarm kill pile"))(g)  # pragma: no mutate
            case TransferHP(player, target, amount, source):
                p = g.players[player]
                old_hp = p.hp
                yield from do(Damage(player, amount, source))(g)
                actual = old_hp - p.hp
                if actual > 0:
                    yield from do(Heal(target, actual, source))(g)
            case StealHP(player, target, amount, source):
                t = g.players[target]
                old_hp = t.hp
                yield from do(Damage(target, amount, source))(g)
                actual = old_hp - t.hp
                if actual > 0:
                    yield from do(Heal(player, actual, source))(g)
            case Resolve(resolver, card, source):
                from combat import resolve_combat
                if card.is_type(CardType.ENEMY):
                    yield from resolve_combat(resolver, card)(g)
                elif card.is_type(CardType.FOOD):
                    yield from do(Eat(resolver, card, "resolve food"))(g)  # pragma: no mutate
                elif card.is_type(CardType.WEAPON):
                    yield from do(Wield(resolver, card, "resolve weapon"))(g)  # pragma: no mutate
                elif card.is_type(CardType.EQUIPMENT):
                    yield from do(Equip(resolver, card, "resolve equipment"))(g)  # pragma: no mutate
                elif card.is_type(CardType.EVENT):
                    yield from do(Discard(resolver, card, "resolve event"))(g)  # pragma: no mutate
            case Eat(player, card, source):
                p = g.players[player]
                if not p.is_satiated:
                    assert card.level is not None
                    yield from do(Heal(player, card.level, "food"))(g)  # pragma: no mutate
                    p.is_satiated = True
                yield from do(Discard(player, card, "food consumed"))(g)  # pragma: no mutate
            case EndPhase(phase):
                g.current_phase = None
                g._event_log.append(PhaseChanged(None))
            case StartPhase(phase):
                g.current_phase = phase
                g._event_log.append(PhaseChanged(phase))
            case GameOver(result):
                g.game_result = result
                g._event_log.append(GameEnded(result))
            case FlipPriority():
                g.priority = other(g.priority)
            case _:  # pragma: no mutate
                raise Exception(f"Action not in list: {action}")  # pragma: no mutate
    return effect

def _player_to_choose_replacement(g: GameState, action: Action) -> PID:
    if isinstance(action, (Damage, Heal, SetHP)):
        return action.target
    return g.priority

def _fire_triggers(g: GameState, action: Action, kind: TKind) -> Negotiation:
    triggered = [ tr for tr in _get_triggers(g, action) if tr.kind == kind ]
    if not triggered:
        return

    if len(triggered) > 1:
        pid = _player_to_choose_replacement(g, action)
        pb = PromptBuilder(f"Order {kind} triggers for {action}:")  # pragma: no mutate
        for tr in triggered:
            pb.add(TextOption(tr.name))
        response = yield pb.build(pid)
        chosen = response[pid]
        assert isinstance(chosen, TextOption)
        idx = next(i for i, tr in enumerate(triggered) if tr.name == chosen.text)
        triggered.insert(0, triggered.pop(idx))

    for tr in triggered:
        yield from tr.callback(action)(g)

def _get_triggers(g: GameState, action: Action) -> list[Trait]:
    traits: list[Trait] = []

    for pid in PID:
        p = g.players[pid]
        for slot in [p.equipment, p.discard, p.hand, p.sidebar,
                     *p.action_field.slots_in_fill_order()]:
            for card in slot.cards:
                for trait in card.traits:
                    traits.append(trait)
        for ws in p.weapon_slots:
            if ws.weapon is not None:
                for trait in ws.weapon.traits:
                    traits.append(trait)
            for card in ws.killstack.cards:
                for trait in card.traits:
                    traits.append(trait)

    for trait in g.active_traits:
        traits.append(trait)

    return [trait for trait in traits if trait.applies(action)]