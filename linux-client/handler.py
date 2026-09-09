"""Dispatches validated protocol messages to an InputBackend."""

from protocol import ProtocolError, parse_message, MSG_MOVE, MSG_CLICK, MSG_SCROLL, MSG_KEY


def handle_message(raw: dict, backend) -> None:
    """Validate one decoded message and dispatch it to the backend.

    Never raises on malformed input: logs and returns, so one bad frame
    doesn't drop the whole connection.
    """
    try:
        msg = parse_message(raw)
    except ProtocolError as exc:
        print(f"[handler] dropping malformed message: {exc}")
        return

    if msg["t"] == MSG_MOVE:
        backend.move(msg["dx"], msg["dy"])
    elif msg["t"] == MSG_CLICK:
        backend.click(msg.get("button", "left"), msg.get("action", "click"))
    elif msg["t"] == MSG_SCROLL:
        backend.scroll(msg["dy"])
    elif msg["t"] == MSG_KEY:
        backend.key(msg["code"], msg["action"], msg.get("mods", []))
