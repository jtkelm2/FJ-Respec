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

A connection represents one **player** (RED or BLUE) for the duration of one game. The server tells the player which side they are via a `notify` message immediately after the catalog (see §3). There is no separate handshake or authentication step.

---

## 2. Session lifecycle

A complete game session, from the perspective of one client, proceeds as follows:

```
1. Client opens transport to server.
2. Server → catalog        (exactly one)
3. Server → notify         ("You are <Role> (RED|BLUE)")
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

After the catalog, the server SHOULD send a `notify` describing the player's role and side, but this is advisory — clients MUST NOT depend on a specific notify being present.

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
    "self": {
      "hand": "red_hand",
      "deck": "red_deck",
      "refresh": "red_refresh",
      "discard": "red_discard",
      "sidebar": "red_sidebar",
      "equipment": "red_equipment",
      "action_field_top_distant": "red_action_field_top_distant",
      "action_field_top_hidden": "red_action_field_top_hidden",
      "action_field_bottom_hidden": "red_action_field_bottom_hidden",
      "action_field_bottom_distant": "red_action_field_bottom_distant",
      "ws_0_weapon": "red_ws_0_weapon",
      "ws_0_killstack": "red_ws_0_killstack"
    },
    "opponent": { ... },
    "shared": {
      "guard_deck": "guard_deck"
    }
  },
  "weapon_slots": {
    "self": { "ws_0": "red_ws_0" },
    "opponent": { "ws_0": "blue_ws_0" },
    "shared": {}
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

#### 3.1.2 Slot catalog

`slots` is a JSON object with three keys: `"self"`, `"opponent"`, and `"shared"`. Each maps **semantic role** (e.g. `"hand"`, `"deck"`, `"action_field_top_distant"`) to the slot's **wire name** (e.g. `"red_hand"`).

The client uses the semantic role to know *what* a slot is (my hand, opponent's deck, etc.) and the wire name to look up its contents in `state` messages and to interpret `prompt` options that reference slots.

Weapon-internal slots (the weapon card holder and kill stack per weapon slot) also appear here, keyed by roles like `"ws_0_weapon"` and `"ws_0_killstack"`.

#### 3.1.3 Weapon slot catalog

`weapon_slots` has the same `self`/`opponent`/`shared` structure. Each entry maps a role (e.g. `"ws_0"`) to the weapon slot's wire name (e.g. `"red_ws_0"`). Used to interpret `weapon_slot` options in prompts.

#### 3.1.4 Catalog stability

The catalog is sent **once** and is **immutable** for the rest of the session. Card names, slot names, and weapon slot names in `state` and `prompt` messages always reference entries from this catalog.

### 3.2 `state`

Sent whenever the visible game state for this player has changed. Carries a complete fog-of-war snapshot — the client SHOULD treat it as an authoritative replacement, not a delta.

```json
{
  "type": "state",
  "view": {
    "hp": 18,
    "slots": {
      "red_hand": ["food_5", "enemy_3", "weapon_2"],
      "red_deck": 25,
      "red_equipment": ["human"],
      "blue_deck": 28,
      "blue_equipment": 1,
      "blue_action_field_top_hidden": 2,
      "guard_deck": 14,
      ...
    },
    "weapons": [
      {"name": "red_ws_0", "card": "weapon_5", "sharpness": 5, "kills": 0}
    ],
    "opp_weapons": [
      {"name": "blue_ws_0", "sharpness": 3, "kills": 1}
    ],
    "priority": "RED",
    "game_result": null
  }
}
```

#### View fields

| Field          | Type                            | Description                                                                                     |
| -------------- | ------------------------------- | ----------------------------------------------------------------------------------------------- |
| `hp`           | int                             | This player's current hit points.                                                               |
| `slots`        | object                          | Slot name → contents. See §3.2.1.                                                               |
| `weapons`      | array of weapon objects         | This player's weapon slots. See §3.2.2.                                                         |
| `opp_weapons`  | array of opponent weapon objects| Opponent's weapon slots. See §3.2.3.                                                            |
| `priority`     | string                          | `"RED"` or `"BLUE"`. Whose priority it currently is.                                            |
| `game_result`  | object \| null                  | `null` during play. When non-null: `{"winners": [...], "outcome": "<OUTCOME>"}`. See §3.2.4.    |

#### 3.2.1 Slots

The `slots` object is keyed by **slot wire name** (as established in the catalog). The value is one of:

- **`list[string]`** — visible slot contents. Each string is a card name referencing the card catalog. Order matches the engine's internal order.
- **`int`** — count-only (fog of war). The client can see how many cards are present but not their identities.

Which slots are visible and which are count-only is determined by fog-of-war rules:

| Slot type                             | Own view      | Opponent's view |
| ------------------------------------- | ------------- | --------------- |
| hand, equipment, sidebar              | card list     | count           |
| deck, refresh, discard                | count         | count           |
| action field distant (top/bottom)     | card list     | card list       |
| action field hidden (top/bottom)      | card list     | count           |
| weapon/killstack slots                | (via weapons) | count           |
| guard deck                            | count         | count           |

#### 3.2.2 Own weapons

Each entry in `weapons`:

| Field      | Type           | Description                                          |
| ---------- | -------------- | ---------------------------------------------------- |
| `name`     | string         | Weapon slot wire name (e.g. `"red_ws_0"`).           |
| `card`     | string \| null | Card name of the equipped weapon, or `null` if empty.|
| `sharpness`| int            | Current sharpness value.                             |
| `kills`    | int            | Number of enemies on the kill stack.                 |

#### 3.2.3 Opponent weapons

Each entry in `opp_weapons`:

| Field      | Type   | Description                                          |
| ---------- | ------ | ---------------------------------------------------- |
| `name`     | string | Weapon slot wire name (e.g. `"blue_ws_0"`).          |
| `sharpness`| int    | Current sharpness value (public information).         |
| `kills`    | int    | Number of enemies on the kill stack (public).         |

Note: opponent weapon card identity is hidden.

#### 3.2.4 Game result

When non-null:

| Field     | Type            | Description                                                      |
| --------- | --------------- | ---------------------------------------------------------------- |
| `winners` | array of string | Subset of `["RED", "BLUE"]`. May be empty.                       |
| `outcome` | string          | One of the outcome constants (see below).                        |

Outcome values: `MUTUAL_GOOD_WIN`, `GOOD_KILLED_EVIL`, `EVIL_KILLED_GOOD`, `GOOD_KILLED_GOOD`, `EXHAUSTION`, `GOOD_GOOD_MUTUAL_DEATH`, `GOOD_EVIL_MUTUAL_DEATH`, `GOOD_THWARTED`, `EVIL_THWARTED`.

### 3.3 `prompt`

Asks the player to choose one option.

```json
{
  "type": "prompt",
  "text": "Choose a card to discard:",
  "options": [
    {"type": "card", "slot": "red_hand", "index": 0},
    {"type": "card", "slot": "red_hand", "index": 2},
    {"type": "text", "text": "Cancel"}
  ]
}
```

| Field     | Type              | Notes                                                            |
| --------- | ----------------- | ---------------------------------------------------------------- |
| `text`    | string            | Player-facing prompt text. May be empty.                         |
| `options` | array of *Option* | Non-empty. The client must respond with one of these (see §5.1). |

#### 3.3.1 Option types

| Option type     | Schema                                                    | Meaning                                                                                                                              |
| --------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `text`          | `{"type": "text", "text": <string>}`                      | A free-text choice (e.g. `"Yes"`, `"Cancel"`, `"Pass"`). Render the `text` field as the label.                                      |
| `card`          | `{"type": "card", "slot": <string>, "index": <int>}`      | Choose a specific card by its location. `slot` is a slot wire name, `index` is the position within that slot. The client can look up the card name from the last `state` message to render it, or display the slot name and index. |
| `slot`          | `{"type": "slot", "name": <string>}`                      | Choose a slot. `name` is a slot wire name from the catalog.                                                                          |
| `weapon_slot`   | `{"type": "weapon_slot", "name": <string>}`               | Choose a weapon slot. `name` is a weapon slot wire name from the catalog.                                                            |

Receivers MUST tolerate unknown option `type` values by treating them as opaque (still echoing them back faithfully if chosen).

### 3.4 `notify`

A non-interactive informational message.

```json
{"type": "notify", "text": "You are Human (RED)"}
```

The client SHOULD display the text. It MUST NOT respond.

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
2. Render `state` messages without blocking on user input. State updates may arrive while a prompt is pending.
3. Respond to each `prompt` with exactly one `response`, echoing one of the offered options unchanged.
4. Tolerate unknown message types and unknown option types by ignoring them gracefully.
5. Stop sending after receiving `close`.

A **conformant client** MAY:

1. Send `resign`, `draw_offer`, `draw_accept` at any time after the catalog.
2. Close the transport at any time (treated as forfeit).

A **conformant server** MUST:

1. Send `catalog` as its first message, listing every card template, slot, and weapon slot that may appear.
2. Send a fresh `state` whenever the player's visible game state changes (or at least before each prompt).
3. Maintain at most one outstanding `prompt` per client (P1).
4. Match responses to prompts in order (P3).
5. Not introduce new names after the initial catalog.
6. Send a final `state` (with `game_result` populated) and a `close` at the end of the session.

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
