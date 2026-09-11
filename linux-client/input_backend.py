"""Backends that turn protocol events into real (or fake) input.

InputBackend is the interface handler.py dispatches to. MockBackend
records calls for tests. UinputBackend is the real thing — it only
imports evdev inside __init__, not at module load time, so the rest of
the codebase (and its tests) can run on machines without evdev installed
or without /dev/uinput access.
"""

from abc import ABC, abstractmethod


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
        capabilities = {
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL],
            e.EV_KEY: (
                [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE]
                + [getattr(e, name) for name in KEY_MAP.values()]
                + [getattr(e, name) for name in MOD_MAP.values()]
            ),
        }
        self._ui = evdev.UInput(capabilities, name="remote-hid-virtual-input")

    def move(self, dx, dy):
        e = self._e
        self._ui.write(e.EV_REL, e.REL_X, int(dx))
        self._ui.write(e.EV_REL, e.REL_Y, int(dy))
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
        self._ui.write(e.EV_REL, e.REL_WHEEL, int(dy))
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
