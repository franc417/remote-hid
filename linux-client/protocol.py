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


# The phone closes an older desktop session with this exact reason when a
# newer one connects (WsServer.kt must use the same text). A client that
# sees it knows it was taken over deliberately, not dropped by the network,
# and must NOT auto-reconnect, or two desktops would fight over one phone.
REPLACED_REASON = "replaced by a newer connection"


class SessionReplaced(Exception):
    """The phone handed this session to a newer connection."""


def make_field_message(focused: bool, text: str = "", caret: int = 0, password: bool = False, name: str = "") -> dict:
    """Desktop -> phone: the state of the focused text field, so the phone's
    typing bar shows what is really in the box (see fieldwatch.py).
    `focused` False means no text field has focus (the bar hides). `caret` is
    an index into `text`. For a password field `text` is only bullets."""
    if not isinstance(focused, bool):
        raise ProtocolError("field.focused must be a boolean")
    if not focused:
        return {"t": "field", "focused": False}
    if not isinstance(text, str):
        raise ProtocolError("field.text must be a string")
    if not isinstance(caret, int) or isinstance(caret, bool) or caret < 0:
        raise ProtocolError("field.caret must be a non-negative integer")
    return {
        "t": "field", "focused": True, "text": text, "caret": min(caret, len(text)),
        "password": bool(password), "name": str(name or ""),
    }


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
