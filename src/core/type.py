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
     
class Slot:
  name: str
  _cards: list[Card]

  def __init__(self, name: str, cards: list[Card] | None = None):
    self.name = name
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
  name: str
  _weapon_slot: Slot
  killstack: Slot

  def __init__(self, name: str):
    self.name = name
    self._weapon_slot = Slot(f"{name}_weapon")
    self.killstack = Slot(f"{name}_killstack")

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
  
  def can_fight(self, lvl:int) -> bool:
    if self.weapon is None: return False 
    if self.killstack.is_empty(): return True
    last_enemy_killed = self.killstack.cards[0]
    assert last_enemy_killed.level is not None
    return last_enemy_killed.level >= lvl


############# Options ########

class Option:
  """Base for typed prompt options."""
  pass

@dataclass
class TextOption(Option):
  text: str
  def __str__(self): return self.text  # pragma: no mutate

@dataclass
class CardOption(Option):
  card: Card
  def __str__(self): return self.card.display_name  # pragma: no mutate

@dataclass
class SlotOption(Option):
  slot: Slot
  def __str__(self):  # pragma: no mutate
    if self.slot.is_empty(): return "[empty]"  # pragma: no mutate
    return ", ".join(c.display_name for c in self.slot.cards)  # pragma: no mutate

@dataclass
class WeaponSlotOption(Option):
  weapon_slot: WeaponSlot
  def __str__(self):  # pragma: no mutate
    w = self.weapon_slot.weapon  # pragma: no mutate
    if w is None: return "Empty"  # pragma: no mutate
    return f"{w.display_name} (sharpness {self.weapon_slot.sharpness()})"  # pragma: no mutate


############# Prompt ########

@dataclass
class PromptHalf:
  """A question for one player."""
  text: str
  options: list[Option]

class PKind(Enum):
  BOTH = auto()
  EITHER = auto()

@dataclass
class Prompt:
  for_player: dict[PID,PromptHalf]
  kind: PKind

def Ask(player:PID, text: str, options: list[Option]) -> Prompt:
  return Prompt({player: PromptHalf(text, options)}, PKind.EITHER)  # pragma: no mutate

def AskBoth(asks: dict[PID,PromptHalf]) -> Prompt:
  return Prompt(asks, PKind.BOTH)  # pragma: no mutate

def AskEither(asks: dict[PID,PromptHalf]) -> Prompt:
  return Prompt(asks, PKind.EITHER)

Response = dict[PID, Option]

class PromptBuilder:
  """Accumulates typed Options, builds a Prompt."""

  def __init__(self, text: str):
    self._text = text
    self._options: list[Option] = []

  def add(self, option: Option):
    self._options.append(option)
    return self

  def add_cards(self, cards: "list[Card]"):
    for card in cards:
      self._options.append(CardOption(card))
    return self

  def add_if(self, cond: bool, option: Option):
    if cond:
      self._options.append(option)
    return self

  def _half(self) -> PromptHalf:
    return PromptHalf(self._text, list(self._options))  # pragma: no mutate

  def build(self, pid: PID) -> Prompt:
    return Prompt({pid: self._half()}, PKind.EITHER)  # pragma: no mutate

  @staticmethod
  def both(*builders: "PromptBuilder") -> Prompt:
    if len(builders) == 1:
      half = builders[0]._half()
      return AskBoth({pid: half for pid in PID})  # pragma: no mutate
    return AskBoth({PID.RED: builders[0]._half(), PID.BLUE: builders[1]._half()})  # pragma: no mutate

  @staticmethod
  def either(*builders: "PromptBuilder") -> Prompt:
    if len(builders) == 1:
      half = builders[0]._half()
      return AskEither({pid: half for pid in PID})  # pragma: no mutate
    return AskEither({PID.RED: builders[0]._half(), PID.BLUE: builders[1]._half()})  # pragma: no mutate

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

    def __init__(self, prefix: str):
      self.top_distant = Slot(f"{prefix}_action_field_top_distant")
      self.bottom_distant = Slot(f"{prefix}_action_field_bottom_distant")
      self.top_hidden = Slot(f"{prefix}_action_field_top_hidden")
      self.bottom_hidden = Slot(f"{prefix}_action_field_bottom_hidden")

    def slots_in_fill_order(self) -> list[Slot]:
      return [self.top_distant, self.top_hidden, self.bottom_hidden, self.bottom_distant]

@dataclass
class PlayerState:
    prefix: str  # e.g. "red", "blue" — used to name child slots

    hp: int = 20
    hp_cap: int = 20
    hp_floor: int | None = None
    hp_ceiling: int | None = None
    alignment: Alignment = Alignment.GOOD
    role: Role = field(default_factory=DefaultRole)

    # These are initialized in __post_init__ from prefix
    action_field: ActionField = field(init=False)
    deck: Slot = field(init=False)
    refresh: Slot = field(init=False)
    discard: Slot = field(init=False)
    hand: Slot = field(init=False)
    sidebar: Slot = field(init=False)
    equipment: Slot = field(init=False)
    weapon_slots: list[WeaponSlot] = field(init=False)

    max_equipment: int = 2

    # Per-action-phase tracking
    is_satiated: bool = False
    first_play_done: bool = False
    action_plays_left: int = 3

    # active_traits: frozenset[Trait] = frozenset()

    def __post_init__(self):
        p = self.prefix
        self.action_field = ActionField(p)
        self.deck = Slot(f"{p}_deck")
        self.refresh = Slot(f"{p}_refresh")
        self.discard = Slot(f"{p}_discard")
        self.hand = Slot(f"{p}_hand")
        self.sidebar = Slot(f"{p}_sidebar")
        self.equipment = Slot(f"{p}_equipment")
        self.weapon_slots = [WeaponSlot(f"{p}_ws_0")]

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
    current_phase: Phase | None = None
    game_result: GameResult | None = None

    players: dict[PID,PlayerState] = field(default_factory=dict)

    # Shared
    guard_deck: Slot = field(default_factory=lambda: Slot("guard_deck"))
    action_field: ActionField = field(default_factory=lambda: ActionField("shared"))

    # Event log — drained by the interaction layer between state pushes
    _event_log: list["Event"] = field(default_factory=list)

    def drain_events(self) -> "list[Event]":
        events = list(self._event_log)
        self._event_log.clear()
        return events

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


############# Events ########

class Event:
  """Base for events recorded by the engine during action execution."""
  pass

@dataclass
class CardMoved(Event):
  card: Card
  source: Slot | None
  dest: Slot

@dataclass
class HPChanged(Event):
  target: PID
  old_hp: int
  new_hp: int

@dataclass
class SlotShuffled(Event):
  slot: Slot

@dataclass
class PlayerDied(Event):
  target: PID

@dataclass
class PhaseChanged(Event):
  phase: Phase | None

@dataclass
class GameEnded(Event):
  result: GameResult


############# Player View ########

@dataclass
class PlayerView:
    # Own state (full visibility)
    hp: int
    hand: list[Card]
    equipment: list[Card]
    weapons: list[tuple[Card | None, int, int]]  # (weapon, sharpness, kill_count)
    deck_size: int
    refresh_size: int
    discard_size: int
    action_field_top_distant: list[Card]
    action_field_top_hidden: list[Card]
    action_field_bottom_hidden: list[Card]
    action_field_bottom_distant: list[Card]
    sidebar: list[Card]

    # Opponent state (fog of war)
    opp_deck_size: int
    opp_action_field_top_distant: list[Card]
    opp_action_field_bottom_distant: list[Card]

    # Shared
    current_phase: Phase | None
    priority: PID
    guard_deck_size: int
    game_result: GameResult | None


def compute_player_view(g: GameState, pid: PID) -> PlayerView:
    p = g.players[pid]
    opp = g.players[other(pid)]

    weapons = []
    for ws in p.weapon_slots:
        weapons.append((ws.weapon, ws.sharpness(), len(ws.killstack.cards)))

    return PlayerView(
        hp=p.hp,
        hand=list(p.hand.cards),
        equipment=list(p.equipment.cards),
        weapons=weapons,
        deck_size=len(p.deck.cards),
        refresh_size=len(p.refresh.cards),
        discard_size=len(p.discard.cards),
        action_field_top_distant=list(p.action_field.top_distant.cards),
        action_field_top_hidden=list(p.action_field.top_hidden.cards),
        action_field_bottom_hidden=list(p.action_field.bottom_hidden.cards),
        action_field_bottom_distant=list(p.action_field.bottom_distant.cards),
        sidebar=list(p.sidebar.cards),

        opp_deck_size=len(opp.deck.cards),
        opp_action_field_top_distant=list(opp.action_field.top_distant.cards),
        opp_action_field_bottom_distant=list(opp.action_field.bottom_distant.cards),

        current_phase=g.current_phase,
        priority=g.priority,
        guard_deck_size=len(g.guard_deck.cards),
        game_result=g.game_result,
    )