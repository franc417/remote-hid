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


## Desktop -> phone: `field` (typing bar)

The WebSocket is two-way. Besides the phone's input events, the desktop client sends the state of the
text field that currently has keyboard focus, so the phone's typing bar shows what is really in the box
(not a guess from the keys that were tapped).

```json
{"t": "field", "focused": true, "text": "hello wor", "caret": 9, "password": false, "name": "Search"}
{"t": "field", "focused": false}
```

- `focused` (required, boolean): false means no text field has focus; nothing else is sent and the bar hides.
- `text`: the caret's own line, trimmed to a window around the caret with `…` where it was cut.
- `caret`: index into `text` (0 to length).
- `password`: true for a password box. `text` is then only bullet characters (the real text is never read
  or sent), and the phone shows bullets regardless.
- `name`: the field's accessible name (often its label), shown as a caption.

The newest state wins: if the link is slow, intermediate states are dropped rather than queued. A desktop
that cannot read text fields (no AT-SPI) simply never sends this message, and the phone falls back to a local
echo of the keys it sent.
