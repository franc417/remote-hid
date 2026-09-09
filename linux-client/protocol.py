"""Wire protocol for phone -> desktop input events.

Messages are single-line JSON objects sent over the WebSocket connection.
See ../PROTOCOL.md for the full spec.
"""

MSG_MOVE = "move"
MSG_CLICK = "click"
MSG_SCROLL = "scroll"
MSG_KEY = "key"

VALID_TYPES = {MSG_MOVE, MSG_CLICK, MSG_SCROLL, MSG_KEY}
VALID_BUTTONS = {"left", "right", "middle"}
VALID_CLICK_ACTIONS = {"click", "down", "up"}
VALID_KEY_ACTIONS = {"down", "up"}
VALID_MODIFIERS = {"ctrl", "alt", "shift", "meta"}


class ProtocolError(ValueError):
    """Raised when an incoming message fails validation."""


def parse_message(raw: dict) -> dict:
    """Validate a decoded JSON message and return it if well-formed.

    Raises ProtocolError with a human-readable reason on anything
    malformed, so the caller can log-and-skip instead of crashing the
    connection over one bad frame.
    """
    if not isinstance(raw, dict):
        raise ProtocolError("message is not a JSON object")

    msg_type = raw.get("t")
    if msg_type not in VALID_TYPES:
        raise ProtocolError(f"unknown message type: {msg_type!r}")

    if msg_type == MSG_MOVE:
        _require_number(raw, "dx")
        _require_number(raw, "dy")

    elif msg_type == MSG_CLICK:
        button = raw.get("button", "left")
        if button not in VALID_BUTTONS:
            raise ProtocolError(f"invalid button: {button!r}")
        action = raw.get("action", "click")
        if action not in VALID_CLICK_ACTIONS:
            raise ProtocolError(f"invalid click action: {action!r}")

    elif msg_type == MSG_SCROLL:
        _require_number(raw, "dy")

    elif msg_type == MSG_KEY:
        if not isinstance(raw.get("code"), str):
            raise ProtocolError("key message missing string 'code'")
        action = raw.get("action")
        if action not in VALID_KEY_ACTIONS:
            raise ProtocolError(f"invalid key action: {action!r}")
        mods = raw.get("mods", [])
        if not isinstance(mods, list) or any(m not in VALID_MODIFIERS for m in mods):
            raise ProtocolError(f"invalid modifiers: {mods!r}")

    return raw


def _require_number(raw: dict, field: str) -> None:
    value = raw.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProtocolError(f"'{field}' must be a number, got {value!r}")
