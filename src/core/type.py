from dataclasses import dataclass, field
from random import Random
from typing import Callable, Generator
from enum import Enum, auto
from abc import abstractmethod

class CardType(Enum):
  WEAPON = auto()
  EQUIPMENT = auto()
  ENEMY = auto()
  FOOD = auto()

@dataclass
class Card:
  name: str
  display_name: str
  text: str
  level: int | None
  types: tuple[CardType, ...]
  is_elusive: bool
  is_first: bool

  def is_type(self,typ:CardType) -> bool:
    return typ in list(self.types)

class PID(Enum):
  RED  = auto()
  BLUE = auto()

def other(pid:PID) -> PID:
  match pid:
    case PID.RED:  return PID.BLUE
    case PID.BLUE: return PID.RED

@dataclass
class Prompt:
  pass

Response = dict[PID,int]

@dataclass
class Ask(Prompt):
  pid: PID
  text: str
  options: list[str]

@dataclass
class AskBoth(Prompt):
  text: dict[PID,str]
  options: dict[PID,list[str]]

  def only(self,pid:PID) -> Ask:
    return Ask(pid,self.text[pid],self.options[pid])

class Slot:
  _cards: list[Card]

  def __init__(self, cards: list[Card] | None = None):
    self._cards = cards or []
  
  @property
  def cards(self):
    return self._cards

  def deslot(self, card:Card):
    assert card in self._cards
    self._cards.remove(card)
  
  def slot(self, card:Card):
    self._cards.insert(0, card)


class WeaponSlot:
  weapon: Card | None
  killstack: Slot

  def __init__(self):
    self.weapon = None
    self.killstack = Slot()

  def sharpness(self) -> int:
    if not self.killstack.cards: return 0
    return self.killstack.cards[0].level or 0

class Alignment(Enum):
  GOOD = auto()
  EVIL = auto()

@dataclass
class Role:
  name:str
  alignment:Alignment

class DefaultRole(Role):
  def __init__(self,good=True):
    self.name = "Human" if good else "???"
    self.alignment = Alignment.GOOD if good else Alignment.EVIL


@dataclass
class ActionField:
    top_distant: Slot
    bottom_distant: Slot
    top_hidden: Slot
    bottom_hidden: Slot

    def __init__(self):
      self.top_distant = Slot()
      self.bottom_distant = Slot()
      self.top_hidden = Slot()
      self.bottom_hidden = Slot()

@dataclass
class PlayerState:
    hp: int = 20
    hp_cap: int = 20
    hp_floor: int | None = None
    hp_ceiling: int | None = None
    alignment: Alignment = Alignment.GOOD
    role: Role = DefaultRole()
    action_field: ActionField = ActionField()
    # permanent_traits: frozenset[Trait] = frozenset()

    deck: Slot = Slot()
    refresh: Slot = Slot()
    discard: Slot = Slot()
    hand: Slot = Slot()
    manipulation_field: list[Slot] = []

    equipment: list[Slot] = [Slot(), Slot()]
    weapon_slots: list[WeaponSlot] = [WeaponSlot()]

    # Per-action-phase tracking
    # has_eaten_this_phase: bool = False
    # action_plays_made: int = 0
    # devil_used_this_phase: bool = False
    # sun_used_this_phase: bool = False

    # active_traits: frozenset[Trait] = frozenset()

    # Flags
    is_dead: bool = False
    # action_phase_over: bool = False

@dataclass
class GameState:
    rng: Random

    # phase: Phase
    # phase_context: PhaseContext
    priority: PID
    # game_result: GameResult | None

    players: dict[PID,PlayerState]

    # Shared
    guard_deck: Slot
    action_field: ActionField

    def all_slots(self) -> list[Slot]:
        slots: list[Slot] = [self.guard_deck]
        for af in [self.action_field]:
            slots += [af.top_distant, af.bottom_distant, af.top_hidden, af.bottom_hidden]
        for p in self.players.values():
            slots += [p.deck, p.refresh, p.discard, p.hand]
            slots += p.equipment
            slots += p.manipulation_field
            for ws in p.weapon_slots:
                slots.append(ws.killstack)
            paf = p.action_field
            slots += [paf.top_distant, paf.bottom_distant, paf.top_hidden, paf.bottom_hidden]
        return slots

    def deslot(self, card: Card):
        for slot in self.all_slots():
            if card in slot.cards:
                slot.deslot(card)
                return
        raise ValueError(f"Card {card} not found in any slot")

# An effect is a "negotiated" GameState
Effect = Callable[[GameState], Generator[Prompt, Response, GameState]]

def compose(*effects) -> Effect:
    def composed(g: GameState) -> Generator[Prompt, Response, GameState]:
        for eff in effects:
            g = yield from eff(g)
        return g
    return composed

############# Actions ########

@dataclass
class Action:
  pass

@dataclass
class SetHP(Action):
  target: PID
  value: int
  source: str = ""

@dataclass
class Damage(Action):
  target: PID
  amount: int
  source: str = ""

@dataclass
class Heal(Action):
  target: PID
  amount: int
  source: str = ""

@dataclass
class Death(Action):
  target: PID
  source: str = ""

@dataclass
class Slay(Action):
  slayer: PID
  enemy: Card
  ws: WeaponSlot | None   # weapon vs. fists
  source: str = ""

@dataclass
class Discard(Action):
  discarder: PID
  card: Card
  source: str = ""

############ Traits ##############################

class TKind(Enum):
  BEFORE = auto()
  REPLACEMENT = auto()
  AFTER = auto()

@dataclass
class Trait:
    name: str
    callback: Callable[[Action], Effect]
    kind: TKind