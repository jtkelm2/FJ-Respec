from dataclasses import dataclass, field
from random import Random
from typing import Callable, Generator
from enum import Enum, auto

class CardType(Enum):
  WEAPON = auto()
  EQUIPMENT = auto()
  ENEMY = auto()
  FOOD = auto()
  EVENT = auto()

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
  return Prompt({player: PromptHalf(text, options)}, PKind.EITHER)  # pragma: no mutate

def AskBoth(asks: dict[PID,PromptHalf]) -> Prompt:
  return Prompt(asks, PKind.BOTH)  # pragma: no mutate

def AskEither(asks: dict[PID,PromptHalf]) -> Prompt:
  return Prompt(asks, PKind.EITHER)

Response = dict[PID,int]

class Slot:
  _cards: list[Card]

  def __init__(self, cards: list[Card] | None = None):
    self._cards = []
    if cards is not None: self.slot(*cards)
  
  @property   # property metadata thwarts attempts to directly modify cards; use API instead
  def cards(self):
    return self._cards
  
  @property
  def is_first(self) -> bool:
    return any(card.is_first for card in self.cards)

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
  _weapon_slot: Slot
  killstack: Slot

  def __init__(self):
    self._weapon_slot = Slot()
    self.killstack = Slot()

  @property
  def weapon(self) -> Card | None:
    return None if self._weapon_slot.is_empty() else self._weapon_slot.cards[0]

  def wield(self, card: Card):
    """Place card as the weapon in this slot. Encapsulates _weapon_slot access."""
    self._weapon_slot.slot(card)

  def sharpness(self) -> int:
    if self.weapon is None: return 0
    assert isinstance(self.weapon.level, int)
    if not self.killstack.cards: return self.weapon.level
    return min(self.weapon.level, self.killstack.cards[0].level or 0)  # pragma: no mutate

class Alignment(Enum):
  GOOD = auto()
  EVIL = auto()

@dataclass
class Role:
  name:str
  alignment:Alignment

class DefaultRole(Role):
  def __init__(self,good=True):  # pragma: no mutate
    self.name = "Human" if good else "???"  # pragma: no mutate
    self.alignment = Alignment.GOOD if good else Alignment.EVIL  # pragma: no mutate


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
    sidebar: Slot = field(default_factory=Slot)

    equipment: Slot = field(default_factory=Slot)
    max_equipment: int = 2
    weapon_slots: list[WeaponSlot] = field(default_factory=lambda: [WeaponSlot()])

    # Per-action-phase tracking
    is_satiated: bool = False
    first_play_done: bool = False
    action_plays_left: int = 3

    # active_traits: frozenset[Trait] = frozenset()

    # Flags
    is_dead: bool = False
    claims_world_killed: bool = False

class Outcome(Enum):
    MUTUAL_GOOD_WIN = auto()
    GOOD_KILLED_EVIL = auto()
    EVIL_KILLED_GOOD = auto()
    GOOD_KILLED_GOOD = auto()
    EXHAUSTION = auto()
    GOOD_GOOD_MUTUAL_DEATH = auto()
    GOOD_EVIL_MUTUAL_DEATH = auto()
    GOOD_THWARTED = auto()
    EVIL_THWARTED = auto()

@dataclass
class GameResult:
    winners: tuple[PID, ...]
    outcome: Outcome

class Phase(Enum):
    REFRESH = auto()
    MANIPULATION = auto()
    ACTION = auto()

WORLD_NAME = "the_world"  # pragma: no mutate

@dataclass
class GameState:
    rng: Random

    priority: PID
    game_result: GameResult | None = None

    players: dict[PID,PlayerState] = field(default_factory=dict)

    # Shared
    guard_deck: Slot = field(default_factory=Slot)
    action_field: ActionField = field(default_factory=ActionField)

    def shuffle(self,slot:Slot):
       slot.shuffle(self.rng)

    @property
    def is_over(self) -> bool:
        return self.game_result is not None

    def get_worlds_killed(self) -> int:
        count = 0
        for p in self.players.values():
            for card in p.discard.cards:
                if card.name == WORLD_NAME:
                    count += 1
            for ws in p.weapon_slots:
                for card in ws.killstack.cards:
                    if card.name == WORLD_NAME:
                        count += 1
        return count

    def check_game_over(self) -> GameResult | None:
        """Determine game result from current state. Returns None if game continues."""
        dead = [pid for pid in PID if self.players[pid].is_dead]
        good = {pid : self.players[pid].alignment == Alignment.GOOD for pid in PID}

        if len(dead) == 2:
            if all(good.values()):
                return GameResult((), Outcome.GOOD_GOOD_MUTUAL_DEATH)
            else:
                return GameResult((), Outcome.GOOD_EVIL_MUTUAL_DEATH)

        if len(dead) == 1:
            deceased = dead[0]
            survivor = other(deceased)

            if good[deceased]:
                # A Good player died — all Good players lose, Evil wins
                if good[survivor]:
                    return GameResult((), Outcome.GOOD_KILLED_GOOD)
                return GameResult((survivor,), Outcome.EVIL_KILLED_GOOD)
            else:
                # Evil player died — Good wins
                return GameResult((survivor,), Outcome.GOOD_KILLED_EVIL)

        if not all(self.players[pid].claims_world_killed for pid in PID):
           return None

        if not self.get_worlds_killed() >= 2:
            if all(good.values()):
                return GameResult((), Outcome.GOOD_THWARTED)
            return GameResult(tuple(pid for pid in PID if good[pid]), Outcome.EVIL_THWARTED)
           
        if all(good.values()):
           return GameResult(tuple(PID), Outcome.MUTUAL_GOOD_WIN)
        return GameResult(tuple(pid for pid in PID if good[pid]), Outcome.EVIL_THWARTED)

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
  source: str = ""  # pragma: no mutate

@dataclass
class Damage(Action):
  target: PID
  amount: int
  source: str = ""  # pragma: no mutate

@dataclass
class Heal(Action):
  target: PID
  amount: int
  source: str = ""  # pragma: no mutate

@dataclass
class Death(Action):
  target: PID
  source: str = ""  # pragma: no mutate

@dataclass
class Slay(Action):
  slayer: PID
  enemy: Card
  ws: WeaponSlot | None   # weapon vs. fists
  source: str = ""  # pragma: no mutate

@dataclass
class Discard(Action):
  discarder: PID
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class Refresh(Action):
  card: Card
  player: PID
  source: str = ""  # pragma: no mutate

@dataclass
class EnsureDeck(Action):
   player: PID
   source: str = ""  # pragma: no mutate

@dataclass
class Shuffle(Action):
   slot: Slot
   source: str = ""  # pragma: no mutate

@dataclass
class ShuffleRefreshIntoDeck(Action):
  player: PID
  source: str = ""  # pragma: no mutate

@dataclass
class Draw(Action):
  player: PID         # who receives the card
  # from_player: PID    # whose deck to draw from
  source: str = ""  # pragma: no mutate

@dataclass
class Slot2Slot(Action):
   orig: Slot
   dest: Slot
   source: str = ""  # pragma: no mutate

@dataclass
class Slot2SlotAll(Action):
   orig: Slot
   dest: Slot
   source: str = ""  # pragma: no mutate

@dataclass
class SlotCard(Action):
   card: Card
   slot: Slot
   source: str = ""  # pragma: no mutate

@dataclass
class TransferHP(Action):
  player: PID
  target: PID
  amount: int
  source: str = ""  # pragma: no mutate

@dataclass
class StealHP(Action):
  player: PID
  target: PID
  amount: int
  source: str = ""  # pragma: no mutate

@dataclass
class Equip(Action):
  player: PID
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class Wield(Action):
  player: PID
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class Disarm(Action):
  player: PID
  source: str = ""  # pragma: no mutate

@dataclass
class Resolve(Action):
  resolver: PID
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class Eat(Action):
  player: PID
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class StartPhase(Action):
  phase: Phase
  source: str = ""  # pragma: no mutate

@dataclass
class EndPhase(Action):
  phase: Phase
  source: str = ""

@dataclass
class GameOver(Action):
  result: GameResult
  source: str = ""  # pragma: no mutate

@dataclass
class FlipPriority(Action):
  source: str = ""  # pragma: no mutate

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