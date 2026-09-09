# Wire protocol

Messages are single-line JSON objects, one per WebSocket text frame, sent
from the phone (server) to the desktop (client).

Every message has a `t` field naming its type.

## `move`

Relative cursor movement, sent continuously while dragging on the
trackpad.

```json
{"t": "move", "dx": 12, "dy": -4}
```

- `dx`, `dy` — number. Pixels of relative movement since the last event.

## `click`

```json
{"t": "click", "button": "left", "action": "click"}
```

- `button` — one of `left`, `right`, `middle`. Defaults to `left`.
- `action` — one of `click` (press + release), `down`, `up`. Defaults to
  `click`. `down`/`up` are separate so the client can support
  click-and-drag (send `down`, then a stream of `move`, then `up`).

## `scroll`

```json
{"t": "scroll", "dy": -3}
```

- `dy` — number. Positive scrolls down, negative scrolls up (matches
  natural/reversed scroll direction used by most trackpads).

## `key`

```json
{"t": "key", "code": "KeyV", "action": "down", "mods": ["ctrl"]}
```

- `code` — string. A key identifier, e.g. `KeyA`, `Digit1`, `Enter`,
  `ArrowUp`. See `linux-client/input_backend.py`'s `KEY_MAP` for the
  currently supported set.
- `action` — `down` or `up`. Sent as a pair for a normal keypress, or a
  single `down` while a key is held.
- `mods` — array, zero or more of `ctrl`, `alt`, `shift`, `meta`. Sent
  with the key event rather than as separate messages, since sticky
  modifiers on the phone side are applied to the *next* key rather than
  held as their own down/up pair.

## Malformed messages

A client that receives a message it can't parse (wrong types, unknown
`t`, missing required field) must log and drop it, not crash the
connection — one bad frame shouldn't end the session. See
`linux-client/protocol.py::parse_message` and
`linux-client/handler.py::handle_message`.
