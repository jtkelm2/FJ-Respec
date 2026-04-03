from dataclasses import dataclass, field
from random import Random
from typing import Callable, Generator
from enum import Enum, auto

class CardType(Enum):
  WEAPON = auto()
  EQUIPMENT = auto()
  ENEMY = auto()
  FOOD = auto()

@dataclass(eq=False)
class Card:
  name: str
  display_name: str
  text: str
  level: int | None
  types: tuple[CardType, ...]
  is_elusive: bool
  is_first: bool
  slot: "Slot | None" = None

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
class PromptHalf:
  """A question for one player."""
  text: str
  options: list[str]

class PKind(Enum):
  BOTH = auto()
  EITHER = auto()

@dataclass
class Prompt:
  for_player: dict[PID,PromptHalf]
  kind: PKind

def Ask(player:PID, text: str, options: list[str]) -> Prompt:
  return Prompt({player: PromptHalf(text, options)}, PKind.EITHER)

def AskBoth(asks: dict[PID,PromptHalf]) -> Prompt:
  return Prompt(asks, PKind.BOTH)

def AskEither(asks: dict[PID,PromptHalf]) -> Prompt:
  return Prompt(asks, PKind.EITHER)

Response = dict[PID,int]

class Slot:
  _cards: list[Card]

  def __init__(self, cards: list[Card] | None = None):
    self._cards = []
    if cards is not None: self.slot(*cards)
  
  @property
  def cards(self):
    return self._cards

  def deslot(self, *cards:Card):
    for card in cards:
      assert card in self._cards
      assert card.slot is self
      card.slot = None
      self._cards.remove(card)

  def slot(self, *cards:Card):
    for card in cards:
      if card.slot is not None:
         card.slot.deslot(card)
      card.slot = self
      self._cards.insert(0, card)

  def draw(self) -> Card:
    assert self._cards
    card = self._cards.pop(0)
    card.slot = None
    return card

  def is_empty(self) -> bool:
    return len(self._cards) == 0
  
  def shuffle(self,rng:Random):
     rng.shuffle(self._cards)

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

    def slots_in_fill_order(self) -> list[Slot]:
      return [self.top_distant, self.top_hidden, self.bottom_hidden, self.bottom_distant]

@dataclass
class PlayerState:
    hp: int = 20
    hp_cap: int = 20
    hp_floor: int | None = None
    hp_ceiling: int | None = None
    alignment: Alignment = Alignment.GOOD
    role: Role = field(default_factory=DefaultRole)
    action_field: ActionField = field(default_factory=ActionField)
    # permanent_traits: frozenset[Trait] = frozenset()

    deck: Slot = field(default_factory=Slot)
    refresh: Slot = field(default_factory=Slot)
    discard: Slot = field(default_factory=Slot)
    hand: Slot = field(default_factory=Slot)
    manipulation_field: Slot = field(default_factory=Slot)

    equipment: Slot = field(default_factory=Slot)
    weapon_slots: list[WeaponSlot] = field(default_factory=lambda: [WeaponSlot()])

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

    def shuffle(self,slot:Slot):
       slot.shuffle(self.rng)

# An effect is a "negotiated" GameState
Negotiation = Generator[Prompt, Response, None]
Effect = Callable[[GameState], Negotiation]

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

@dataclass
class Refresh(Action):
  card: Card
  player: PID
  source: str = ""

@dataclass
class EnsureDeck(Action):
   player: PID
   source: str = ""

@dataclass
class Shuffle(Action):
   slot: Slot
   source: str = ""

@dataclass
class ShuffleRefreshIntoDeck(Action):
  player: PID
  source: str = ""

@dataclass
class Draw(Action):
  player: PID         # who receives the card
  # from_player: PID    # whose deck to draw from
  source: str = ""

@dataclass
class Slot2Slot(Action):
   orig: Slot
   dest: Slot
   source: str = ""

@dataclass
class Slot2SlotAll(Action):
   orig: Slot
   dest: Slot
   source: str = ""

@dataclass
class SlotCard(Action):
   card: Card
   slot: Slot
   source: str = ""

@dataclass
class DealToActionField(Action):
  player: PID
  card: Card
  slot: Slot
  source: str = ""

@dataclass
class FlipPriority(Action):
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