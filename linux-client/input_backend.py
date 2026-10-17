"""Backends that turn protocol events into real (or fake) input.

InputBackend is the interface handler.py dispatches to. MockBackend
records calls for tests. UinputBackend is the real thing — it only
imports evdev inside __init__, not at module load time, so the rest of
the codebase (and its tests) can run on machines without evdev installed
or without /dev/uinput access.
"""

import os
from abc import ABC, abstractmethod


def _env_float(name: str, default: float) -> float:
    """Tuning knob from the environment; a typo falls back to the default
    rather than breaking input."""
    try:
        value = float(os.environ.get(name, default))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


class Carry:
    """Turns fractional deltas into whole counts without losing the rest.

    The phone sends fractional pixel deltas (0.7, 0.3, ...). The kernel only
    takes whole counts, and plain int() truncates toward zero, so a slow
    drag made of sub-pixel steps produced NO movement at all and a fast one
    lost up to a count per event: the cursor felt sluggish and "stuck" at low
    speed. Keeping the remainder and adding it to the next delta makes the
    total distance exact.
    """

    def __init__(self) -> None:
        self._rest = 0.0

    def take(self, value: float) -> int:
        total = self._rest + value
        whole = int(total)  # toward zero, so the remainder keeps the sign
        self._rest = total - whole
        return whole


class InputBackend(ABC):
    @abstractmethod
    def move(self, dx, dy) -> None: ...

    @abstractmethod
    def click(self, button: str, action: str = "click") -> None: ...

    @abstractmethod
    def scroll(self, dy) -> None: ...

    @abstractmethod
    def key(self, code: str, action: str, mods: list) -> None: ...

    def close(self) -> None:
        """Releases any resources held by the backend. Default is a
        no-op — MockBackend needs no cleanup; UinputBackend overrides
        this to actually close the virtual device."""


class MockBackend(InputBackend):
    """Records calls instead of touching real hardware. Used in tests."""

    def __init__(self):
        self.calls = []

    def move(self, dx, dy):
        self.calls.append(("move", dx, dy))

    def click(self, button, action="click"):
        self.calls.append(("click", button, action))

    def scroll(self, dy):
        self.calls.append(("scroll", dy))

    def key(self, code, action, mods):
        self.calls.append(("key", code, action, tuple(mods)))


# Wire-protocol key codes -> evdev key names. Covers letters, digits,
# common editing/navigation keys. Extend as the Android keyboard grows
# more keys (F-row, numpad, punctuation, etc).
KEY_MAP = {}
for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEY_MAP[f"Key{_letter}"] = f"KEY_{_letter}"
for _digit in "0123456789":
    KEY_MAP[f"Digit{_digit}"] = f"KEY_{_digit}"
KEY_MAP.update({
    "Enter": "KEY_ENTER",
    "Backspace": "KEY_BACKSPACE",
    "Space": "KEY_SPACE",
    "Tab": "KEY_TAB",
    "Escape": "KEY_ESC",
    "ArrowUp": "KEY_UP",
    "ArrowDown": "KEY_DOWN",
    "ArrowLeft": "KEY_LEFT",
    "ArrowRight": "KEY_RIGHT",
    "Comma": "KEY_COMMA",
    "Period": "KEY_DOT",
    "Minus": "KEY_MINUS",
    "Equal": "KEY_EQUAL",
    "PrintScreen": "KEY_SYSRQ",
    "Home": "KEY_HOME",
    "End": "KEY_END",
    "PageUp": "KEY_PAGEUP",
    "PageDown": "KEY_PAGEDOWN",
    "Meta": "KEY_LEFTMETA",
    "Semicolon": "KEY_SEMICOLON",
    "Quote": "KEY_APOSTROPHE",
    "Slash": "KEY_SLASH",
    "Backslash": "KEY_BACKSLASH",
    "BracketLeft": "KEY_LEFTBRACE",
    "BracketRight": "KEY_RIGHTBRACE",
    "Backquote": "KEY_GRAVE",
})
for _n in range(1, 13):
    KEY_MAP[f"F{_n}"] = f"KEY_F{_n}"

MOD_MAP = {
    "ctrl": "KEY_LEFTCTRL",
    "alt": "KEY_LEFTALT",
    "shift": "KEY_LEFTSHIFT",
    "meta": "KEY_LEFTMETA",
}


class UinputBackend(InputBackend):
    """Injects input via a virtual device through the kernel's uinput
    interface. Requires evdev to be installed and /dev/uinput to be
    writable by the running user (root, or a udev rule granting access).
    """

    def __init__(self):
        import evdev
        from evdev import ecodes as e

        self._e = e
        # REL_WHEEL_HI_RES (120 units per notch) is what lets libinput scroll
        # smoothly instead of in whole notches; older python-evdev/kernels
        # lack it, in which case scrolling falls back to notches with carry.
        self._hi_res = getattr(e, "REL_WHEEL_HI_RES", None)
        rel_axes = [e.REL_X, e.REL_Y, e.REL_WHEEL]
        if self._hi_res is not None:
            rel_axes.append(self._hi_res)
        self._init_motion()
        capabilities = {
            e.EV_REL: rel_axes,
            e.EV_KEY: (
                [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE]
                + [getattr(e, name) for name in KEY_MAP.values()]
                + [getattr(e, name) for name in MOD_MAP.values()]
            ),
        }
        self._ui = evdev.UInput(capabilities, name="remote-hid-virtual-input")

    def _init_motion(self):
        self._sensitivity = _env_float("REMOTE_HID_SENSITIVITY", 1.0)
        self._scroll_scale = _env_float("REMOTE_HID_SCROLL_SCALE", 1.0)
        self._x, self._y = Carry(), Carry()
        self._wheel_hi, self._wheel_notch = Carry(), Carry()

    def move(self, dx, dy):
        e = self._e
        ix = self._x.take(dx * self._sensitivity)
        iy = self._y.take(dy * self._sensitivity)
        if ix == 0 and iy == 0:
            return  # still accumulating a sub-count: nothing to send yet
        if ix:
            self._ui.write(e.EV_REL, e.REL_X, ix)
        if iy:
            self._ui.write(e.EV_REL, e.REL_Y, iy)
        self._ui.syn()

    def click(self, button, action="click"):
        e = self._e
        code = {
            "left": e.BTN_LEFT,
            "right": e.BTN_RIGHT,
            "middle": e.BTN_MIDDLE,
        }[button]
        if action in ("click", "down"):
            self._ui.write(e.EV_KEY, code, 1)
            self._ui.syn()
        if action in ("click", "up"):
            self._ui.write(e.EV_KEY, code, 0)
            self._ui.syn()

    def scroll(self, dy):
        e = self._e
        units = dy * self._scroll_scale  # 1.0 unit == one wheel notch
        if self._hi_res is not None:
            hi = self._wheel_hi.take(units * 120)
            if hi == 0:
                return
            self._ui.write(e.EV_REL, self._hi_res, hi)
            # Kernel convention: also emit the legacy whole-notch event each
            # time 120 hi-res units have accumulated; libinput uses the
            # hi-res axis when it exists and ignores this one.
            notch = self._wheel_notch.take(hi / 120.0)
            if notch:
                self._ui.write(e.EV_REL, e.REL_WHEEL, notch)
        else:
            notch = self._wheel_notch.take(units)
            if notch == 0:
                return
            self._ui.write(e.EV_REL, e.REL_WHEEL, notch)
        self._ui.syn()

    def key(self, code, action, mods):
        e = self._e
        value = 1 if action == "down" else 0

        for m in mods:
            mod_name = MOD_MAP.get(m)
            if mod_name:
                self._ui.write(e.EV_KEY, getattr(e, mod_name), value)

        key_name = KEY_MAP.get(code)
        if key_name is None:
            self._ui.syn()
            return  # unknown key — skip rather than crash the connection

        self._ui.write(e.EV_KEY, getattr(e, key_name), value)
        self._ui.syn()

    def close(self):
        self._ui.close()
