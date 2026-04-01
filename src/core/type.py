from dataclasses import dataclass, field
from typing import Callable, Generator
from enum import Enum, auto
from abc import abstractmethod

class CardType(Enum):
  WEAPON = auto()
  EQUIPMENT = auto()
  ENEMY = auto()
  FOOD = auto()

class Card:
  name: str
  display_name: str
  text: str
  level: int | None
  types: tuple[CardType, ...]
  is_elusive: bool
  is_first: bool

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

class Alignment(Enum):
  GOOD = auto()
  EVIL = auto()

class Role:
  name:str
  alignment:Alignment

class DefaultRole(Role):
  def __init__(self,good=True):
    self.name = "Human" if good else "???"
    self.alignment = Alignment.GOOD if good else Alignment.EVIL

class Slot:
  cards: list[Card]

  def __init__(self):
    self.cards = []

class WeaponSlot:
  weapon: Card | None
  killstack: Slot

  def __init__(self):
    self.weapon = None
    self.killstack = Slot()

  def sharpness(self) -> int:
    return 0 # TODO

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

    deck: list[Card] = []
    refresh_pile: list[Card] = []
    discard_pile: list[Card] = []
    hand: list[Card] = []
    manipulation_field: list[Card] = []

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
    rng_seed: int

    # phase: Phase
    # phase_context: PhaseContext
    priority: PID
    # game_result: GameResult | None

    players: dict[PID,PlayerState]

    # Shared
    guard_deck: list[Card]
    action_field: ActionField

# An effect is a "negotiated" GameState
Effect = Callable[[GameState], Generator[Prompt, Response, GameState]]

def compose(*effects) -> Effect:
    def composed(g: GameState) -> Generator[Prompt, Response, GameState]:
        for eff in effects:
            g = yield from eff(g)
        return g
    return composed

class TKind(Enum):
  BEFORE = auto()
  REPLACEMENT = auto()
  AFTER = auto()

@dataclass
class Trait:
    name: str
    callback: Callable[[Action], Effect]
    kind: TKind