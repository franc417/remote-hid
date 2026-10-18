"""Mirrors the desktop's focused text field to the phone.

The phone's typing bar used to be a local echo: it remembered which keys had
been tapped, so it was wrong the moment you deleted something, clicked
elsewhere, used autocomplete, or typed into a different box. This module
reads the REAL focused text field through the desktop's accessibility bus
(AT-SPI) and sends its text and caret position to the phone, which shows
exactly what is in the box you are typing in, and nothing when no text box
is focused.

Layers, so almost all of it is testable without a desktop:
  FieldSnapshot / snapshot_message   what to say about a field (pure)
  FieldWatcher                       dedupes and forwards to whoever listens
  LatestBox                          thread-safe "newest message wins" handoff
  AtspiBackend                       the only part that touches AT-SPI

Privacy: a password field's text is never read. Only its length is, and the
phone gets that many bullet characters.

Needs (optional, the phone falls back to its local echo without them):
  Arch:   pacman -S python-gobject at-spi2-core
  Debian: apt install python3-gi gir1.2-atspi-2.0 at-spi2-core
Browsers and Electron apps only expose their text boxes when accessibility is
on: the backend asks for it, and `gsettings set org.gnome.desktop.interface
toolkit-accessibility true` makes it permanent on GNOME.
"""

import asyncio
import os
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from protocol import make_field_message

BULLET = "\u2022"
MAX_PASSWORD_BULLETS = 64
CHARS_BEFORE_CARET = 120
CHARS_AFTER_CARET = 60


@dataclass(frozen=True)
class FieldSnapshot:
    focused: bool
    text: str = ""
    caret: int = 0
    password: bool = False
    name: str = ""


def window_text(text: str, caret: int, before: int = CHARS_BEFORE_CARET, after: int = CHARS_AFTER_CARET) -> Tuple[str, int]:
    """The part of `text` worth showing on a phone-sized bar: the caret's own
    line, trimmed to `before` characters either side of the caret, with an
    ellipsis where it was cut. Returns (shown_text, caret_inside_shown_text)."""
    caret = max(0, min(caret, len(text)))
    line_start = text.rfind("\n", 0, caret) + 1
    newline = text.find("\n", caret)
    line_end = len(text) if newline == -1 else newline
    line = text[line_start:line_end]
    c = caret - line_start
    start = max(0, c - before)
    end = min(len(line), c + after)
    shown = line[start:end]
    c -= start
    if start > 0:
        shown = "\u2026" + shown
        c += 1
    if end < len(line):
        shown += "\u2026"
    return shown, c


def snapshot_message(snap: FieldSnapshot) -> dict:
    """The wire message for a snapshot. Masks passwords here as well, so even a
    backend that passed real text through could not leak it."""
    if not snap.focused:
        return make_field_message(False)
    if snap.password:
        masked = BULLET * min(len(snap.text), MAX_PASSWORD_BULLETS)
        return make_field_message(True, masked, len(masked), True, snap.name)
    shown, caret = window_text(snap.text, snap.caret)
    return make_field_message(True, shown, caret, False, snap.name)


class FieldWatcher:
    """Turns backend snapshots into messages for one listener (`sink`),
    skipping repeats. Whoever connects to the phone installs itself as the
    sink and immediately receives the current state."""

    def __init__(self, backend):
        self._backend = backend
        self._lock = threading.Lock()
        self._sink: Optional[Callable[[dict], None]] = None
        self._last: Optional[dict] = None
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._backend.start(self._on_snapshot)

    def set_sink(self, sink: Optional[Callable[[dict], None]]) -> None:
        with self._lock:
            self._sink = sink
            current = self._last if self._last is not None else make_field_message(False)
        if sink is not None:
            sink(current)  # a new connection learns the current state at once

    def _on_snapshot(self, snap: FieldSnapshot) -> None:
        msg = snapshot_message(snap)
        with self._lock:
            if msg == self._last:
                return
            self._last = msg
            sink = self._sink
        if sink is not None:
            sink(msg)


class LatestBox:
    """Newest message wins. put() is safe from any thread (the accessibility
    callbacks run on a GLib thread); get() is awaited on the asyncio loop.
    If the phone's link is slow, stale intermediate states are dropped instead
    of piling up, so the bar never lags behind what you typed."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._event = asyncio.Event()
        self._value: Optional[dict] = None

    def put(self, msg: dict) -> None:
        try:
            self._loop.call_soon_threadsafe(self._set, msg)
        except RuntimeError:
            pass  # loop already closed: the session is over

    def _set(self, msg: dict) -> None:
        self._value = msg
        self._event.set()

    async def get(self) -> dict:
        await self._event.wait()
        self._event.clear()
        value, self._value = self._value, None
        return value


# ---------------------------------------------------------------- AT-SPI

class AtspiBackend:
    """Reads the focused editable text field through AT-SPI. Not unit tested
    (it needs a desktop session); everything above it is."""

    EVENTS = (
        "object:state-changed:focused",
        "object:text-changed:insert",
        "object:text-changed:delete",
        "object:text-caret-moved",
    )

    def __init__(self):
        self._focused = None
        self._on_snapshot = None
        self._Atspi = None
        self._GLib = None

    @staticmethod
    def unavailable_reason() -> Optional[str]:
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi  # noqa: F401
        except (ImportError, ValueError) as exc:
            return f"PyGObject / AT-SPI bindings not installed ({exc})"
        return None

    def start(self, on_snapshot) -> None:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GLib

        self._Atspi, self._GLib, self._on_snapshot = Atspi, GLib, on_snapshot
        if Atspi.init() >= 2:
            raise RuntimeError("could not connect to the accessibility bus")
        try:
            Atspi.set_timeout(800, 800)  # a hung app must not freeze the preview
        except Exception:
            pass
        self._enable_accessibility()
        listener = Atspi.EventListener.new(self._on_event)
        for name in self.EVENTS:
            listener.register(name)
        self._listener = listener  # keep a reference alive
        threading.Thread(target=GLib.MainLoop().run, name="atspi-loop", daemon=True).start()

    def _enable_accessibility(self) -> None:
        """Browsers/Electron only build their accessibility tree once the
        session says accessibility is wanted. Best effort."""
        try:
            from gi.repository import Gio, GLib
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync(
                "org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties", "Set",
                GLib.Variant("(ssv)", ("org.a11y.Status", "IsEnabled", GLib.Variant("b", True))),
                None, Gio.DBusCallFlags.NONE, 2000, None,
            )
        except Exception:
            pass

    def _is_editable_text(self, src) -> bool:
        A = self._Atspi
        try:
            if not src.get_state_set().contains(A.StateType.EDITABLE):
                return False
            A.Text.get_character_count(src)  # raises if it has no text interface
            return True
        except Exception:
            return False

    def _on_event(self, event, *_ignored) -> None:
        A = self._Atspi
        try:
            kind = event.type
            src = event.source
            if kind.startswith("object:state-changed:focused"):
                if event.detail1 == 1:
                    self._focused = src if self._is_editable_text(src) else None
                elif self._focused is not None and src == self._focused:
                    self._focused = None
            elif self._focused is None or src != self._focused:
                # A text event from a field we never saw gain focus (it was
                # already focused when we started): adopt it if it is focused.
                if self._is_editable_text(src) and src.get_state_set().contains(A.StateType.FOCUSED):
                    self._focused = src
                else:
                    return
            self._on_snapshot(self._read())
        except Exception:
            self._on_snapshot(FieldSnapshot(False))

    def _read(self) -> FieldSnapshot:
        A = self._Atspi
        src = self._focused
        if src is None:
            return FieldSnapshot(False)
        try:
            password = src.get_role() == A.Role.PASSWORD_TEXT
            count = A.Text.get_character_count(src)
            caret = A.Text.get_caret_offset(src)
            name = src.get_name() or ""
            if password:
                return FieldSnapshot(True, BULLET * min(count, MAX_PASSWORD_BULLETS), min(caret, count), True, name)
            start = max(0, caret - 4 * CHARS_BEFORE_CARET)
            end = min(count, caret + 4 * CHARS_AFTER_CARET)
            return FieldSnapshot(True, A.Text.get_text(src, start, end) or "", caret - start, False, name)
        except Exception:
            self._focused = None  # the field went away under us
            return FieldSnapshot(False)


_watcher: Optional[FieldWatcher] = None
_watcher_tried = False


def get_watcher() -> Optional[FieldWatcher]:
    """The process-wide watcher, or None when it cannot work here (no AT-SPI
    bindings, no accessibility bus, or REMOTE_HID_NO_FIELD=1). Never raises:
    a missing preview must not break the connection."""
    global _watcher, _watcher_tried
    if _watcher_tried:
        return _watcher
    _watcher_tried = True
    if os.environ.get("REMOTE_HID_NO_FIELD"):
        return None
    reason = AtspiBackend.unavailable_reason()
    if reason:
        print(f"[fieldwatch] typing preview from the desktop is off: {reason}")
        return None
    try:
        watcher = FieldWatcher(AtspiBackend())
        watcher.start()
        _watcher = watcher
    except Exception as exc:
        print(f"[fieldwatch] typing preview from the desktop is off: {exc}")
    return _watcher
