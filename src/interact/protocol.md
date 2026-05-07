# Fool's Journey — Remote Player Wire Protocol

## Context

The engine speaks to remote players (humans or bots) through a thin wire boundary. The contract between server and client is defined here as a self-contained protocol specification. Together with a plain-English understanding of the game rules, it should be sufficient to:

- Build a new frontend (web, mobile, native, AI) compatible with any conformant server without reading engine code.
- Build a new server transport (WebSocket, gRPC, message queue, in-process) without reading any frontend code.

---

## 1. Transport assumptions

The protocol assumes an **ordered, reliable, bidirectional, message-oriented byte stream** between exactly two endpoints (one server, one client). It does not assume TCP specifically — any transport meeting these requirements (WebSockets, Unix domain sockets, an in-process pipe) will work.

### 1.1 Framing

Each protocol message is a single JSON object encoded as UTF-8, terminated by a single newline byte (`\n`). No JSON object may contain a literal newline; the receiver splits the byte stream on `\n` and parses each fragment as JSON.

### 1.2 Message envelope

Every message — in either direction — is a JSON object with a `"type"` field whose value is a known string (`catalog`, `state`, `prompt`, `notify`, `close`, `response`, `resign`, `draw_offer`, `draw_accept`). The remaining fields are determined by the type. Receivers MUST tolerate (ignore) unknown top-level fields and SHOULD log unknown `type` values.

### 1.3 Connection identity

A connection represents one **player** (RED or BLUE) for the duration of one game. All player references on the wire — slot ownership, event targets, view player blocks, priority, winners — are absolute PIDs (`"RED"` / `"BLUE"`); there is no relative `"self"` / `"opponent"` framing. The catalog itself is identical for both clients. Each client learns which side it is on from a `pid_assignment` notify (§3.4.2) sent by the server immediately after the catalog.

---

## 2. Session lifecycle

A complete game session, from the perspective of one client, proceeds as follows:

```
1. Client opens transport to server.
2. Server → catalog        (exactly one)
3. Server → notify {kind: "pid_assignment"}   (exactly one, before any state/prompt)
4. ── game loop ──
   Server → state          (zero or more, before each prompt)
   Server → notify         (zero or more, at any time)
   Server → prompt         → Client → response
   ...
5. Server → state          (final state, with game_result populated)
6. Server → close
7. Server closes transport.
```

### 2.1 Pre-game phase

The very first server-to-client message of every session MUST be a `catalog`. No other server-to-client message may precede it. The catalog establishes the naming space used by all subsequent messages. A client receiving any other message before a catalog SHOULD treat it as a protocol error.

The second message MUST be a `notify` with `kind: "pid_assignment"` (§3.4.2), telling the client which absolute PID (`"RED"` or `"BLUE"`) it is playing. The client MUST receive this before any `state` or `prompt`, since correctly interpreting subsequent messages depends on knowing one's own PID.

The first in-game phase after these two preamble messages is `SETUP` (see §3.2). During setup, the server assigns each player a role and alignment — the client learns its role/alignment from the next `state` message's `view.players[<own_pid>]` block, and from the `card_moved` event that places the role card into the player's equipment. Setup MAY also yield prompts (e.g. role-selection menus in future variants); these follow the normal prompt/response protocol.

### 2.2 Game loop

The game loop interleaves `state`, `notify`, and `prompt` messages from the server with `response` messages from the client. The ordering rules are:

- Multiple `state` messages may arrive consecutively, each replacing the previous one.
- `notify` messages may arrive at any time and require no response.
- A `prompt` message MUST be answered by exactly one `response` message before the next prompt for this player can arrive (§5).
- The server MAY interleave `state` messages between a `prompt` and the corresponding `response` — the client MUST continue to render those state updates without blocking on the user.

### 2.3 End of game

The end of a session is signaled by a `state` message whose `view.game_result` field is non-null, followed by a `close` message, followed by the server closing the transport. After receiving `close`, the client MUST NOT send any further messages. The client MAY close the transport at any time (this is treated as a disconnection — see §6).

---

## 3. Server → Client messages

### 3.1 `catalog`

Sent exactly once, as the first message of the session. Provides three things: card template metadata, slot identity, and weapon slot identity. All names introduced here are stable for the rest of the session.

The catalog is **identical for both clients** — it does not encode the receiving player's identity. It is purely the shared communication vocabulary; per-client identity is established by the immediately-following `pid_assignment` notify (§3.4.2).

```json
{
  "type": "catalog",
  "cards": {
    "enemy_3": {
      "name": "enemy_3",
      "display_name": "Enemy (3)",
      "text": "",
      "level": 3,
      "types": ["ENEMY"],
      "is_elusive": false,
      "is_first": false
    },
    ...
  },
  "slots": {
    "red_hand":       {"owner": "RED",  "role": "hand"},
    "red_deck":       {"owner": "RED",  "role": "deck"},
    "blue_hand":      {"owner": "BLUE", "role": "hand"},
    "guard_deck":     {"owner": null,   "role": "guard_deck"},
    ...
  },
  "weapon_slots": {
    "red_ws_0":  {"owner": "RED",  "role": "ws_0"},
    "blue_ws_0": {"owner": "BLUE", "role": "ws_0"},
    ...
  }
}
```

#### 3.1.1 Card catalog

`cards` is a JSON object keyed by **card name**. All copies of a given card design (e.g. both copies of `enemy_3` in a player's deck) share the same name — card instances are intentionally indistinguishable on the wire.

Per-card fields:

| Field          | Type             | Description                                                                              |
| -------------- | ---------------- | ---------------------------------------------------------------------------------------- |
| `name`         | string           | Canonical identifier. Same as the key. Used in `state` and `prompt` messages.            |
| `display_name` | string           | Player-facing name to render.                                                            |
| `text`         | string           | Player-facing rules text. May be empty.                                                  |
| `level`        | int \| null      | Card level (typically for enemies and weapons). `null` if not applicable.                |
| `types`        | array of string  | Subset of `["WEAPON", "EQUIPMENT", "ENEMY", "FOOD", "EVENT"]`. Primary type first.      |
| `is_elusive`   | bool             | Static gameplay flag.                                                                    |
| `is_first`     | bool             | Static gameplay flag.                                                                    |

The catalog MAY include cards that the player will never see. Clients MUST NOT infer game state from the catalog — only from `state` messages.

In particular, the catalog includes **every possible role card** (one per role in the game's role pool), even though only two are assigned in any given game. This lets the client resolve role-card names it may encounter through `view.role` or `card_moved` events without needing a later catalog update.

#### 3.1.2 Slot catalog

`slots` is a JSON object keyed by **slot wire name**. Each value is a description with two fields:

| Field   | Type            | Description                                                                       |
| ------- | --------------- | --------------------------------------------------------------------------------- |
| `owner` | string \| null  | Absolute PID: `"RED"` or `"BLUE"`. `null` for unowned slots (e.g. `guard_deck`).  |
| `role`  | string          | Semantic role (e.g. `"hand"`, `"deck"`, `"action_field_top_distant"`).            |

The client uses `owner` + `role` (compared against its own PID, learned from `pid_assignment`) to know *what* a slot is and whether it belongs to itself, the opponent, or neither. The wire name (the key) is what subsequent `state` messages and `prompt` options reference.

Weapon-internal slots (the weapon card holder and kill stack per weapon slot) also appear here, with roles like `"ws_0_weapon"` and `"ws_0_killstack"`.

#### 3.1.3 Weapon slot catalog

`weapon_slots` has the same flat structure as `slots`: keyed by **wire name**, each value has `owner` and `role`. Used to interpret `weapon_slot` options in prompts.

#### 3.1.4 Catalog stability

The catalog is sent **once** and is **immutable** for the rest of the session. Card names, slot names, and weapon slot names in `state` and `prompt` messages always reference entries from this catalog.

### 3.2 `state`

Sent whenever the visible game state for this player has changed. Carries a complete fog-of-war snapshot — the client SHOULD treat it as an authoritative replacement, not a delta.

```json
{
  "type": "state",
  "view": {
    "players": {
      "RED":  {"role": "Human", "alignment": "GOOD", "hp": 18},
      "BLUE": {"role": null,    "alignment": null,   "hp": null}
    },
    "slots": {
      "red_hand": [{"name": "food_5", "counters": 0}, {"name": "enemy_3", "counters": 0}, {"name": "weapon_2", "counters": 0}],
      "red_deck": 25,
      "red_equipment": [{"name": "human"}],
      "blue_action_field_top_distant": [{"name": "enemy_5", "counters": 2}],
      "red_ws_0_weapon": [{"name": "weapon_5", "counters": 1}],
      "red_ws_0_killstack": [{"name": "enemy_3"}],
      "guard_deck": 14,
      ...
    },
    "current_phase": "ACTION",
    "priority": "RED",
    "game_result": null
  }
}
```

#### View fields

| Field           | Type           | Description                                                                                        |
| --------------- | -------------- | -------------------------------------------------------------------------------------------------- |
| `players`       | object         | Map of PID (`"RED"`, `"BLUE"`) → per-player block. Both keys are always present. See below.        |
| `slots`         | object         | Slot wire name → contents. See §3.2.1.                                                             |
| `current_phase` | string \| null | Current game phase: `"SETUP"`, `"REFRESH"`, `"MANIPULATION"`, `"ACTION"`, or `null` between phases.|
| `priority`      | string         | `"RED"` or `"BLUE"`. Whose priority it currently is.                                               |
| `game_result`   | object \| null | `null` during play. When non-null: `{"winners": [...], "outcome": "<OUTCOME>"}`. See §3.2.2.       |

Each entry in `players` has these fields:

| Field       | Type           | Description                                                                                          |
| ----------- | -------------- | ---------------------------------------------------------------------------------------------------- |
| `role`      | string \| null | Assigned role name (e.g. `"Human"`, `"Corruption"`). `null` for the opponent (hidden info) and for either player before setup completes. |
| `alignment` | string \| null | `"GOOD"` or `"EVIL"`. `null` for the opponent (hidden info) and before setup completes.              |
| `hp`        | int \| null    | Current hit points. `null` for the opponent (hidden info).                                           |

Both `RED` and `BLUE` keys are always present in `players`; the receiving client distinguishes "own" from "opponent" by comparing against the PID it received in `pid_assignment`. Hidden values (e.g. opponent role/alignment/hp) are surfaced as `null` rather than omitted, so the shape is uniform.

The client learns its role/alignment from `view.players[<own_pid>]` in the first `state` message that arrives after setup. The role string correlates with a card `name` in the `catalog` — the role card placed into the player's equipment at setup has that exact name. See §3.1.1 for how the catalog lists every possible role card, not just the two assigned this game.

Per-weapon-slot info (the wielded weapon card and the kill stack) lives in `slots`, keyed by `<side>_ws_<n>_weapon` (a card list of length 0 or 1) and `<side>_ws_<n>_killstack` (a card list). The set of weapon slot names comes from the `weapon_slots` catalog. Sharpness is a derived value the client computes as `min(weapon.level, killstack[0].level)` (or just `weapon.level` if the killstack is empty).

Opponent weapon holders, killstacks, sharpness, and weapon identity are **hidden information**. Opponent equipment, refresh, discard, hand, sidebar, and hidden action field slots are also hidden.

#### 3.2.1 Slots

The `slots` object is keyed by **slot wire name** (as established in the catalog). The value is one of:

- **`list[object]`** — visible slot contents. Each entry is a card object (see below).
- **`int`** — count-only (fog of war). The client can see how many cards are present but not their identities.

**Hidden slots are omitted entirely** from the `slots` object — their wire names do not appear as keys. A client looking up a hidden slot by name will find nothing. See the visibility table below for which slots are hidden in which direction.

Each card object has these fields:

| Field      | Type   | Description                                                                                                                         |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `name`     | string | Card name referencing the card catalog (§3.1.1).                                                                        |
| `counters` | int    | Number of counters on this card instance.

**Index convention.** Within any slot, **index 0 is the top of the pile** (the card that would be drawn next); higher indices are progressively further down. This applies uniformly to decks, discards, hands, action field slots, killstacks, and weapon holders — anywhere a card list or index appears (in `state` slot contents, `card` option `index` fields, and `card_moved` event `source_index`/`dest_index` fields).

Which slots are visible and which are count-only is determined by fog-of-war rules:

| Slot type                             | Own view      | Opponent's view |
| ------------------------------------- | ------------- | --------------- |
| hand, equipment, sidebar              | card list     | hidden          |
| deck                                  | count         | count           |
| refresh, discard                      | count         | hidden          |
| action field distant (top/bottom)     | card list     | card list       |
| action field hidden (top/bottom)      | card list     | hidden          |
| weapon holder slots                   | card list     | hidden          |
| killstack slots                       | card list     | hidden          |
| guard deck                            | count         | count           |

#### 3.2.2 Game result

When non-null:

| Field     | Type            | Description                                                      |
| --------- | --------------- | ---------------------------------------------------------------- |
| `winners` | array of string | Subset of `["RED", "BLUE"]`. May be empty.                       |
| `outcome` | string          | One of the outcome constants (see below).                        |

Outcome values: `MUTUAL_GOOD_WIN`, `GOOD_KILLED_EVIL`, `EVIL_KILLED_GOOD`, `GOOD_KILLED_GOOD`, `EXHAUSTION`, `GOOD_GOOD_MUTUAL_DEATH`, `GOOD_EVIL_MUTUAL_DEATH`, `GOOD_THWARTED`, `EVIL_THWARTED`.

#### 3.2.3 Events

The `state` message MAY include an `events` array describing what happened since the last state push. Events are **advisory** — the `view` is authoritative. Clients that ignore events still work correctly; clients that process them can animate card movements, HP changes, etc.

```json
{
  "type": "state",
  "view": { ... },
  "events": [
    {"type": "card_moved", "source": "red_hand", "source_index": 0, "dest": "red_discard", "dest_index": 0, "card": {"name": "food_3", "counters": 0}},
    {"type": "card_moved", "source": "blue_deck", "source_index": 0, "dest": "blue_action_field_top_distant", "dest_index": 1, "card": {"name": "enemy_5", "counters": 0}},
    {"type": "slot_transferred", "source": "red_refresh", "dest": "red_deck", "count": 20},
    {"type": "hp_changed", "target": "RED", "old": 20, "new": 15},
    {"type": "slot_shuffled", "slot": "red_deck"},
    {"type": "post_manipulate", "manipulator": "RED", "forced": 1},
    {"type": "player_died", "target": "RED"},
    {"type": "phase_changed", "phase": "ACTION"},
    {"type": "game_ended", "winners": ["RED"], "outcome": "GOOD_KILLED_EVIL"}
  ]
}
```

Event types:

| Event type       | Fields                                                   | Description                                             |
| ---------------- | -------------------------------------------------------- | ------------------------------------------------------- |
| `card_moved`     | `source`, `source_index`, `dest`, `dest_index`, `card?` | A card moved between slots. `source`/`source_index` refer to the state *before* the move; `dest`/`dest_index` refer to the state *after*. `source` and `source_index` are both `null` if the card had no prior slot. The optional `card` field carries the card's identity as a `{"name", "counters"}` object (same shape as a slot entry — see §3.2.1) and is included whenever either the source or the destination slot is card-visible to this player; it is omitted when both endpoints are count-only or hidden. The `card` field lets the client predict the next state from events alone, even when the source is count-only (e.g. drawing from one's own deck). |
| `slot_transferred` | `source`, `dest`, `count`                              | All cards of `source` were moved to `dest` as a batch (e.g., refresh pile shuffled into deck). Clients may animate this as a single batch gesture, rather than N individual card moves. |
| `hp_changed`     | `target`, `old`, `new`                                   | A player's HP changed. `target` is `"RED"` or `"BLUE"`. Per fog-of-war, only emitted for the receiving client's own HP — but the field is included for symmetry with other player-targeted events. |
| `slot_shuffled`  | `slot`                                                   | A slot was shuffled. `slot` is the wire name.           |
| `post_manipulate`| `manipulator`, `forced` (manipulator only, optional)     | The manipulator's `PostManipulate` step ran: a third card was drawn from the opponent's deck, mixed with the two manipulation-field cards, and one of the three placed on the opponent's deck-top with the remaining two sent to opponent's refresh. `manipulator` is `"RED"` or `"BLUE"`. The `forced` field is present **only on the event delivered to the manipulator** and **only when the manipulator forced**: it is the integer index (`0` or `1`) of the card the manipulator chose from their sidebar (before the third card was drawn). The third card's identity is never disclosed to either player by this event. No per-card `card_moved` events are emitted for the moves performed inside `PostManipulate`. |
| `player_died`    | `target`                                                 | A player died. `target` is `"RED"` or `"BLUE"`.         |
| `phase_changed`  | `phase`                                                  | Game phase changed. `phase` is the phase name or `null`.|
| `game_ended`     | `winners`, `outcome`                                     | Game ended with the given result.                       |

The client can cross-reference `source` + `source_index` against the *previous* state snapshot to determine which card moved (for animation); `dest` + `dest_index` can be cross-referenced against the *current* state to locate the card's new position. When the card identity is known to this player (either endpoint card-visible), the `card` field carries it directly so the client need not consult either snapshot to learn the moved card. This is what lets a client maintain its own state purely from the event stream — without the field, a move out of a count-only or hidden source into a card-visible destination (e.g. own draw) would leave the resulting state ambiguous.

Events are fog-of-war filtered per player:
- Card movements where both source and destination are hidden are omitted entirely.
- Own HP changes are visible; opponent HP changes are omitted.
- Shuffles of hidden slots are omitted.
- Deaths, phase changes, and game endings are always visible to both players.

### 3.3 `prompt`

Asks the player to choose one option.

```json
{
  "type": "prompt",
  "text": "Allow opponent to resolve your slot?",
  "options": [
    {"type": "text", "text": "Allow"},
    {"type": "text", "text": "Deny"}
  ],
  "context": [
    {"type": "slot", "name": "red_action_field_top_distant"}
  ]
}
```

| Field     | Type                        | Notes                                                                                     |
| --------- | --------------------------- | ----------------------------------------------------------------------------------------- |
| `text`    | string                      | Player-facing prompt text. May be empty.                                                  |
| `options` | array of *Option*           | Non-empty. The client must respond with one of these (see §5.1).                          |
| `context` | array of *Option* \| absent | Optional. Game objects relevant to the prompt but NOT selectable. Same schema as options. Clients MAY use context to highlight referenced cards/slots visually; clients that ignore `context` still work correctly. The client MUST NOT echo a context option as a response. |

#### 3.3.1 Option types

| Option type     | Schema                                                    | Meaning                                                                                                                              |
| --------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `text`          | `{"type": "text", "text": <string>}`                      | A free-text choice (e.g. `"Yes"`, `"Cancel"`, `"Pass"`). Render the `text` field as the label.                                      |
| `card`          | `{"type": "card", "slot": <string>, "index": <int>}`      | Choose a specific card by its location. `slot` is a slot wire name, `index` is the position within that slot. The client can look up the card entry at `slots[slot][index]` in the last `state` message and read its `name` field to render it. |
| `slot`          | `{"type": "slot", "name": <string>}`                      | Choose a slot. `name` is a slot wire name from the catalog.                                                                          |
| `weapon_slot`   | `{"type": "weapon_slot", "name": <string>}`               | Choose a weapon slot. `name` is a weapon slot wire name from the catalog.                                                            |

Receivers MUST tolerate unknown option `type` values by treating them as opaque (still echoing them back faithfully if chosen).

### 3.4 `notify`

A non-interactive informational message with a structured `kind` subfield.

#### 3.4.1 Info

Unstructured text catchall.

```json
{"type": "notify", "kind": "info", "text": "Some message"}
```

| Field  | Type   | Description            |
| ------ | ------ | ---------------------- |
| `text` | string | Free-text message.     |

#### 3.4.2 PID assignment

Tells the client which absolute PID it is playing for this session.

```json
{"type": "notify", "kind": "pid_assignment", "pid": "RED"}
```

| Field | Type   | Description                  |
| ----- | ------ | ---------------------------- |
| `pid` | string | `"RED"` or `"BLUE"`.         |

Sent **exactly once** per session, **immediately after the `catalog`** and before any `state` or `prompt`. The client MUST process this before interpreting any subsequent message that names a PID, since the catalog itself is symmetric and contains no per-client identity.

The client uses this PID to decide which entries of `view.players` are its own, which catalog `slots` / `weapon_slots` belong to it (`info["owner"] == own_pid`), and how to interpret `priority`, `hp_changed.target`, `player_died.target`, and `winners`.

Clients SHOULD display all notification kinds. Clients MUST NOT respond to any `notify` message. Clients MUST tolerate unknown `kind` values.

### 3.5 `close`

The server signals end-of-session.

```json
{"type": "close"}
```

After sending `close`, the server SHOULD close the transport. After receiving `close`, the client MUST NOT send any further messages and SHOULD release its end of the transport.

---

## 4. Naming

All entities on the wire are identified by **name strings**, not synthetic integer UIDs. Names are established by the catalog at session start and stable for the session.

### 4.1 Card names

A card name (e.g. `"enemy_3"`, `"food_5"`, `"human"`) identifies a card **template**, not an instance. Multiple physical copies of the same card share the same name. This is deliberate — clients cannot distinguish between two copies of `enemy_3`, which prevents information leaks through the wire.

When a specific card instance must be referenced (in `card` options), it is identified by **location**: the slot name plus the index within that slot (see §3.3.1). The client can cross-reference the slot's contents in the most recent `state` message to display the card name.

### 4.2 Slot names

A slot name (e.g. `"red_hand"`, `"blue_action_field_top_distant"`, `"guard_deck"`) identifies a container in the game. The catalog organizes slots by ownership (`self`/`opponent`/`shared`) and semantic role (`hand`, `deck`, etc.), so clients never need to parse the name string itself.

### 4.3 Weapon slot names

A weapon slot name (e.g. `"red_ws_0"`) identifies a weapon slot. Cataloged the same way as regular slots.

### 4.4 Option echoing

Whenever the client sends an option back as part of a `response`, it MUST echo the option dict **exactly** as it received it. The server compares responses by structural equality against the offered options.

---

## 5. Prompt and response semantics

### 5.1 Response messages

In response to a `prompt`, the client sends:

```json
{"type": "response", "option": {"type": "card", "slot": "red_hand", "index": 0}}
```

| Field    | Type   | Notes                                                                                              |
| -------- | ------ | -------------------------------------------------------------------------------------------------- |
| `option` | object | Must be structurally equal to one of the option dicts in the most recent `prompt` for this player. |

### 5.2 Prompt ordering invariants

**P1 — One outstanding prompt per client.** The server MUST NOT send a second `prompt` to a client until the first has been answered.

**P2 — One response per prompt.** The client MUST send exactly one `response` per `prompt`. The client MUST NOT send a `response` without first receiving a `prompt`.

**P3 — Order preservation.** Responses are matched to prompts in the order they were sent.

**P4 — Non-blocking state delivery.** `state` and `notify` messages MAY arrive between a `prompt` and its `response`. The client MUST process them without waiting for the user.

### 5.3 EITHER and BOTH prompts

The engine has two kinds of multi-player prompts (`EITHER` and `BOTH`), but **this distinction is not visible on the wire**. From a single client's perspective, every `prompt` looks the same: a question with options, requiring exactly one response.

In the case of an `EITHER` prompt sent to both players, both clients receive a `prompt`. The server consumes the first response and discards the other. The losing client has no protocol-level obligation beyond P1–P4: respond to every prompt, in order. Discarded responses are silent.

### 5.4 Prompt cancellation

There is no cancellation message. Once a prompt is sent, it is in flight until the client responds. A future revision may add `prompt_cancel`.

---

## 6. Out-of-band client messages

The client MAY send the following messages at any time after the catalog has been received, independently of any pending prompt:

```json
{"type": "resign"}
{"type": "draw_offer"}
{"type": "draw_accept"}
```

| Type           | Meaning                                                                                            |
| -------------- | -------------------------------------------------------------------------------------------------- |
| `resign`       | The player concedes. The server SHOULD end the session with the appropriate game result.           |
| `draw_offer`   | The player offers a draw. The server SHOULD relay this to the opponent (typically as a `notify`).  |
| `draw_accept`  | The player accepts a previously offered draw.                                                      |

These messages do not consume an outstanding prompt. They are advisory signals into the engine's out-of-band channel. A server MAY simply log them; a complete server SHOULD wire them into the engine's resignation / draw machinery.

**Disconnection.** If the client closes the transport without sending `resign`, the server SHOULD treat it as a disconnection (equivalent to a forfeit).

> **Conformance note.** The current server reads OOB messages into `_oob_queue` (see `RemotePlayer._listen` in `player.py`) but does not yet consume them in the game loop.

---

## 7. Conformance summary

A **conformant client** MUST:

1. Receive a `catalog` as the first message and populate its card/slot/weapon-slot lookup tables from it.
2. Receive a `notify` of `kind: "pid_assignment"` as the second message and record its own PID.
3. Render `state` messages without blocking on user input. State updates may arrive while a prompt is pending.
4. Respond to each `prompt` with exactly one `response`, echoing one of the offered options unchanged.
5. Tolerate unknown message types and unknown option types by ignoring them gracefully.
6. Stop sending after receiving `close`.

A **conformant client** MAY:

1. Send `resign`, `draw_offer`, `draw_accept` at any time after the catalog.
2. Close the transport at any time (treated as forfeit).

A **conformant server** MUST:

1. Send `catalog` as its first message, listing every card template, slot, and weapon slot that may appear. The catalog content MUST be identical for both clients (no per-client perspective).
2. Send a `pid_assignment` notify as its second message, telling the client which absolute PID it is playing.
3. Send a fresh `state` whenever the player's visible game state changes (or at least before each prompt).
4. Maintain at most one outstanding `prompt` per client (P1).
5. Match responses to prompts in order (P3).
6. Not introduce new names after the initial catalog.
7. Send a final `state` (with `game_result` populated) and a `close` at the end of the session.

A **conformant server** MAY:

1. Send arbitrary numbers of `notify` and `state` messages at any time.
2. Discard responses to logically-superseded prompts silently.

---

## 8. Implementation files

These files define the current implementation. New servers/clients should not need to read them — this document is self-sufficient — but they are listed for cross-reference:

- `src/interact/connection.py` — `Connection` ABC, `TCPConnection`. Transport abstraction.
- `src/interact/serial.py` — `Serializer`, `Accumulator`. Catalog construction and wire format.
- `src/interact/player.py` — `Player`, `RemotePlayer`, `ScriptedPlayer`, OOB types.
- `src/interact/server.py` — `GameServer` ABC (protocol in `run_game()`), `TCPGameServer`.
- `src/interact/client.py` — `GameClient` ABC (protocol in `run()`), `CLIGameClient`.
- `src/interact/gui_client.py` — `GUIGameClient` (tkinter, non-blocking variant).
- `src/interact/interpret.py` — `AsyncAggregateInterpreter`, `ViewPushingInterpreter`. Prompt routing.
- `src/core/type.py` — `PlayerView`, `Prompt`, `Option`, `GameResult`, `Slot`, `WeaponSlot`.

---

## 9. Verification

Verification is by inspection:

1. Cross-check every message type in §3 and §6 against `conn.send({...})` and `case "..."` sites in `src/interact/`.
2. Cross-check the `state` view structure in §3.2 against `Serializer.player_view` in `serial.py`.
3. Cross-check catalog structure in §3.1 against `Accumulator.catalog` in `serial.py`.
4. Cross-check option types in §3.3.1 against `Serializer.option` in `serial.py`.
5. Cross-check protocol dispatch in `GameClient.run()` and `GameServer.run_game()` against §2 lifecycle.
