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
  is_elusive: bool = False
  is_first: bool = False
  slot: "Slot | None" = None
  counters: int = 0
  traits: "list[Trait]" = field(default_factory=list)
  modifiers: "list[Modifier]" = field(default_factory=list)

  def is_type(self,typ:CardType) -> bool:
    return typ in list(self.types)

class PID(Enum):
  RED  = auto()
  BLUE = auto()

def other(pid:PID) -> PID:
  match pid:
    case PID.RED:  return PID.BLUE
    case PID.BLUE: return PID.RED
     
class SlotKind(Enum):
  DECK = auto()
  REFRESH = auto()
  DISCARD = auto()
  HAND = auto()
  SIDEBAR = auto()
  EQUIPMENT = auto()
  WEAPON = auto()
  KILLSTACK = auto()
  ACTION_FIELD = auto()
  GUARD_DECK = auto()

class Slot:
  name: str
  kind: SlotKind
  owner: PID | None
  _cards: list[Card]

  def __init__(self, name: str, kind: SlotKind, owner: PID | None = None, cards: list[Card] | None = None):
    self.name = name
    self.kind = kind
    self.owner = owner
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

  def slot(self, *cards:Card, at:int=0):
    for card in cards:
      if card.slot is not None:
         card.slot.deslot(card)
      card.slot = self
      self._cards.insert(at, card)

  def draw(self, at:int=0) -> Card:
    assert self._cards
    card = self._cards.pop(at)
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

  def __init__(self, name: str, owner:PID):
    self.name = name
    self._weapon_slot = Slot(f"{name}_weapon", SlotKind.WEAPON, owner)
    self.killstack = Slot(f"{name}_killstack", SlotKind.KILLSTACK, owner)

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
  context: list[Option] = field(default_factory=list)

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
    self._context: list[Option] = []

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

  def context(self, option: Option):
    """Attach a relevant game object for display, not selectable as an option."""
    self._context.append(option)
    return self

  def _half(self) -> PromptHalf:
    return PromptHalf(self._text, list(self._options), list(self._context))  # pragma: no mutate

  def build(self, pid: PID) -> Prompt:
    return Prompt({pid: self._half()}, PKind.EITHER)  # pragma: no mutate
  
  def notify(self):
    return self.add(TextOption("Okay"))
  
  def yesno(self):
    return self.add(TextOption("Yes")).add(TextOption("No"))

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

@dataclass
class ActionField:
    top_distant: Slot
    bottom_distant: Slot
    top_hidden: Slot
    bottom_hidden: Slot

    def __init__(self, pid: PID):
      prefix = "red" if pid is PID.RED else "blue"
      self.top_distant = Slot(f"{prefix}_action_field_top_distant", SlotKind.ACTION_FIELD, owner = pid)
      self.bottom_distant = Slot(f"{prefix}_action_field_bottom_distant", SlotKind.ACTION_FIELD, owner = pid)
      self.top_hidden = Slot(f"{prefix}_action_field_top_hidden", SlotKind.ACTION_FIELD, owner = pid)
      self.bottom_hidden = Slot(f"{prefix}_action_field_bottom_hidden", SlotKind.ACTION_FIELD, owner = pid)

    def slots_in_fill_order(self) -> list[Slot]:
      return [self.top_distant, self.top_hidden, self.bottom_hidden, self.bottom_distant]

@dataclass
class PlayerState:
    pid: PID

    hp: int = 20
    hp_floor: int | None = None
    hp_ceiling: int = 20
    alignment: Alignment | None = None
    role: Role | None = None

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

    def __post_init__(self):
        p = "red" if self.pid is PID.RED else "blue"
        self.action_field = ActionField(self.pid)
        self.deck = Slot(f"{p}_deck", SlotKind.DECK, owner=self.pid)
        self.refresh = Slot(f"{p}_refresh", SlotKind.REFRESH, owner=self.pid)
        self.discard = Slot(f"{p}_discard", SlotKind.DISCARD, owner=self.pid)
        self.hand = Slot(f"{p}_hand", SlotKind.HAND, owner=self.pid)
        self.sidebar = Slot(f"{p}_sidebar", SlotKind.SIDEBAR, owner=self.pid)
        self.equipment = Slot(f"{p}_equipment", SlotKind.EQUIPMENT, owner=self.pid)
        self.weapon_slots = [WeaponSlot(f"{p}_ws_0", owner=self.pid)] 

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
    SETUP = auto()
    REFRESH = auto()
    MANIPULATION = auto()
    ACTION = auto()

WORLD_NAME = "major_21"  # pragma: no mutate

@dataclass
class GameState:
    rng: Random

    priority: PID
    current_phase: Phase | None = None
    game_result: GameResult | None = None

    players: dict[PID,PlayerState] = field(default_factory=dict)

    # Shared
    guard_deck: Slot = field(default_factory=lambda: Slot("guard_deck", SlotKind.GUARD_DECK))

    active_traits: "list[Trait]" = field(default_factory=list)
    active_modifiers: "list[Modifier]" = field(default_factory=list)

    # All role factories available this game. Populated by create_initial_state,
    # read by the wire catalog (so every possible role card is known to clients)
    # and by setup_phase (which picks two via g.rng and instantiates them fresh).
    role_pool: "list[tuple[Callable[[], Card], Role]]" = field(default_factory=list)

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
type Negotiation = Generator[Prompt, Response, None]
type Effect = Callable[[GameState], Negotiation]

type TypedNegotiation[T] = Generator[Prompt, Response, T]
type TypedEffect[T] = Callable[[GameState], TypedNegotiation[T]]

############# Actions ########

class Action:
  excluded_traits: list[str] = []

  def exclude(self, trait_name: str):
     self.excluded_traits.append(trait_name)
     return self

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
  orig: Slot | None = None

  def __post_init__(self):
    if self.orig is None:
      self.orig = self.card.slot

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
  source_index: int = 0
  dest_index: int = 0

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
class SetCounters(Action):
  card: Card
  value: int
  source: str = ""  # pragma: no mutate

@dataclass
class AddCounter(Action):
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class RemoveCounter(Action):
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class ClearCounters(Action):
  card: Card
  source: str = ""  # pragma: no mutate

@dataclass
class DecrementActionPlays(Action):
  player: PID
  source: str = ""  # pragma: no mutate

@dataclass
class EndActionPhase(Action):
  player: PID
  source: str = ""  # pragma: no mutate

@dataclass
class AddToKillstack(Action):
  enemy: Card
  slayer: PID
  killstack: Slot
  source: str = ""  # pragma: no mutate

@dataclass
class AssignRoleCard(Action):
  card: Card
  role: Role
  player: PID
  source: str = ""  # pragma: no mutate

@dataclass
class DistancePenalty(Action):
  player: PID
  source: str = ""  # pragma: no mutate

@dataclass
class FlipPriority(Action):
  source: str = ""  # pragma: no mutate

############ Kill detection ##############################

def would_kill_enemy(action: Action, enemy: Card) -> bool:
    """True if this action represents killing `enemy`. Covers both
    AddToKillstack (weapon kills) and Discard of an enemy card from
    the action Field."""
    match action:
        case AddToKillstack(e, _, _, _) if e is enemy:
            return True
        case Discard(_, c, _, orig) if c is enemy:
            return enemy.is_type(CardType.ENEMY) and orig is not None and orig.kind is SlotKind.ACTION_FIELD
    return False

############ Traits ##############################

class TKind(Enum):
  BEFORE = auto()
  REPLACEMENT = auto()
  AFTER = auto()

@dataclass
class Trait:
    name: str
    kind: TKind
    applies: Callable[[Action], bool]
    callback: Callable[[Action], Effect]

    def instead(self):
      self.kind = TKind.REPLACEMENT
      return self

    @staticmethod
    def on_resolve(card: Card, callback: Callable[[Action], Effect]):
        return Trait(f"{card.display_name} (On Resolve)", TKind.BEFORE,  # pragma: no mutate
                     lambda a: isinstance(a, Resolve) and a.card is card,
                     callback)

    @staticmethod
    def while_equipped(card: Card, kind: TKind,
                       applies: Callable[[Action], bool],
                       callback: Callable[[Action], Effect]):
        inner = applies
        return Trait(f"{card.display_name} (While Equipped)", kind,  # pragma: no mutate
                     lambda a: card.slot is not None
                               and card.slot.kind == SlotKind.EQUIPMENT
                               and inner(a),
                     callback)

    @staticmethod
    def as_a_weapon(card: Card, kind: TKind,
                    applies: Callable[[Action], bool],
                    callback: Callable[[Action], Effect]):
        inner = applies
        return Trait(f"{card.display_name} (As A Weapon)", kind,  # pragma: no mutate
                     lambda a: card.slot is not None
                               and card.slot.kind == SlotKind.WEAPON
                               and inner(a),
                     callback)

    @staticmethod
    def on_discard(card: Card,
                   callback: Callable[[Action], Effect]):
        return Trait(f"{card.display_name} (On Discard)", TKind.AFTER,  # pragma: no mutate
                     lambda a: isinstance(a, Discard) and a.card is card,
                     callback)

    @staticmethod
    def on_kill(card: Card,
                callback: Callable[[Action], Effect]):
        return Trait(f"{card.display_name} (On Kill)", TKind.AFTER,  # pragma: no mutate
                     lambda a: would_kill_enemy(a, card),
                     callback)

    @staticmethod
    def slays_enemy(card: Card, kind: TKind,
                    callback: Callable[[Action], Effect]):
        return Trait(f"{card.display_name} (As A Weapon, On Slay)", kind,
                     lambda a: isinstance(a, Slay) and a.ws is not None and a.ws.weapon is card and
                     card.slot is not None and card.slot.owner is a.slayer,
                     callback)

    @staticmethod
    def on_role_assign(card: Card,
                       setup: "Callable[[PID], Effect]"):
        """AFTER AssignRoleCard: run a one-time setup Effect when this card
        becomes a player's role. The setup Effect may install permanent traits
        onto g.active_traits, execute one-shot actions, or both.

        There should be at most ONE on_role_assign trait per card: multiple
        traits would force a user-visible ordering prompt during setup."""
        def callback(a: Action) -> Effect:
            assert isinstance(a, AssignRoleCard)
            return setup(a.player)
        return Trait(f"{card.display_name} (On Role Assign)", TKind.AFTER,  # pragma: no mutate
                     lambda a: isinstance(a, AssignRoleCard) and a.card is card,
                     callback)

    @staticmethod
    def on_placement(card: Card,
                     callback: Callable[[Action], Effect]):
        return Trait(f"{card.display_name} (On Placement)", TKind.AFTER,  # pragma: no mutate
                     lambda a: (isinstance(a, Slot2Slot)
                                and a.dest.kind == SlotKind.ACTION_FIELD
                                and len(a.dest.cards) > a.dest_index
                                and a.dest.cards[a.dest_index] is card),
                     callback)

    @staticmethod
    def after_death(card: Card,
                    permanent_trait: "Callable[[PID],Trait]"):
        def callback(a: Action) -> Effect:
            def eff(g: GameState) -> Negotiation:
                match a:
                    case AddToKillstack(_, slayer, _, _):
                        g.active_traits.append(permanent_trait(slayer))
                    case Discard(discarder, _, _):
                        g.active_traits.append(permanent_trait(discarder))
                return
                yield  # pragma: no cover
            return eff
        return Trait(f"{card.display_name} (After Death)", TKind.AFTER,  # pragma: no mutate
                     lambda a: would_kill_enemy(a, card),
                     callback)



############ Queries & Modifiers ##############################

@dataclass
class Query:
    @property
    def base(self) -> int:
        raise NotImplementedError  # pragma: no mutate

@dataclass
class Sharpness(Query):
    ws: WeaponSlot
    player: PID

    @property
    def base(self) -> int:
        return self.ws.sharpness()

@dataclass
class EnemyLevel(Query):
    enemy: Card
    ws: WeaponSlot | None

    @property
    def base(self) -> int:
        assert self.enemy.level is not None
        return self.enemy.level

@dataclass
class CanRun(Query):
    player: PID

    @property
    def base(self) -> int:
        return 1

@dataclass
class CanCallGuards(Query):
    player: PID

    @property
    def base(self) -> int:
        return 1

QueryResult = Generator[Prompt, Response, int]

class MKind(Enum):
    INTERCEPT = auto()
    MUTATE = auto()

@dataclass
class Modifier:
    name: str
    kind: MKind
    applies: Callable[[Query], bool]
    callback: Callable[[Query, int], TypedEffect[int]]

    @staticmethod
    def while_equipped(card: Card,
                       applies: Callable[[Query], bool],
                       callback: Callable[[Query, int], TypedEffect[int]]):
        inner = applies
        return Modifier(
            f"{card.display_name} (While Equipped)",  # pragma: no mutate
            MKind.MUTATE,
            lambda q: (card.slot is not None
                       and card.slot.kind == SlotKind.EQUIPMENT
                       and inner(q)),
            callback)

    @staticmethod
    def as_a_weapon(card: Card,
                    applies: Callable[[Query], bool],
                    callback: Callable[[Query, int], TypedEffect[int]]):
        inner = applies
        return Modifier(
            f"{card.display_name} (As A Weapon)",  # pragma: no mutate
            MKind.MUTATE,
            lambda q: (card.slot is not None
                       and card.slot.kind == SlotKind.WEAPON
                       and inner(q)),
            callback)


############# Events ########

class Event:
  """Base for events recorded by the engine during action execution."""
  pass

@dataclass
class CardMoved(Event):
  card: Card
  source: Slot | None
  source_index: int | None  # index in source before the move; None if source was None
  dest: Slot
  dest_index: int           # index in dest after the move

@dataclass
class SlotTransferred(Event):
  """All cards from source were moved to dest as a batch. Emitted by Slot2SlotAll."""
  source: Slot
  dest: Slot
  count: int

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
    # Identity (set after setup phase)
    role: str | None
    alignment: str | None

    # Own state (full visibility)
    hp: int
    hand: list[Card]
    equipment: list[Card]
    weapons: list[tuple[Card | None, int, list[Card]]]  # (weapon, sharpness, killstack cards)
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
        weapons.append((ws.weapon, ws.sharpness(), list(ws.killstack.cards)))

    return PlayerView(
        role=p.role.name if p.role is not None else None,
        alignment=p.alignment.name if p.alignment is not None else None,
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