"""Fractional motion must not be lost between the phone and uinput."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import input_backend  # noqa: E402
from input_backend import Carry, UinputBackend  # noqa: E402


class FakeE:
    EV_REL, EV_KEY = 2, 1
    REL_X, REL_Y, REL_WHEEL, REL_WHEEL_HI_RES = 0, 1, 8, 11


class FakeEOld:  # an evdev/kernel without hi-res scrolling
    EV_REL, EV_KEY = 2, 1
    REL_X, REL_Y, REL_WHEEL = 0, 1, 8


class FakeUI:
    def __init__(self):
        self.events = []
        self.syns = 0

    def write(self, etype, code, value):
        self.events.append((code, value))

    def syn(self):
        self.syns += 1


def make_backend(e=FakeE, env=None):
    b = UinputBackend.__new__(UinputBackend)  # skip evdev/uinput setup
    b._e = e
    b._hi_res = getattr(e, "REL_WHEEL_HI_RES", None)
    b._ui = FakeUI()
    old = {k: os.environ.get(k) for k in ("REMOTE_HID_SENSITIVITY", "REMOTE_HID_SCROLL_SCALE")}
    for k in old:
        os.environ.pop(k, None)
    os.environ.update(env or {})
    try:
        b._init_motion()
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    return b


def total(b, code):
    return sum(v for c, v in b._ui.events if c == code)


def test_carry_never_loses_distance():
    c = Carry()
    assert sum(c.take(0.4) for _ in range(100)) in (39, 40)
    c = Carry()
    assert sum(c.take(-0.4) for _ in range(100)) in (-39, -40)


def test_slow_sub_pixel_drag_still_moves_the_cursor():
    # The old int(dx) turned every one of these into 0: no movement at all.
    b = make_backend()
    for _ in range(50):
        b.move(0.3, 0.0)
    assert 14 <= total(b, FakeE.REL_X) <= 15
    assert total(b, FakeE.REL_Y) == 0


def test_a_fast_drag_is_exact_not_short_by_the_truncated_fraction():
    b = make_backend()
    for _ in range(100):
        b.move(2.7, -1.6)
    assert abs(total(b, FakeE.REL_X) - 270) <= 1
    assert abs(total(b, FakeE.REL_Y) + 160) <= 1


def test_nothing_is_written_while_still_accumulating_a_sub_count():
    b = make_backend()
    b.move(0.2, 0.2)
    assert b._ui.events == [] and b._ui.syns == 0


def test_sensitivity_scales_motion():
    b = make_backend(env={"REMOTE_HID_SENSITIVITY": "2"})
    for _ in range(10):
        b.move(1.0, 0.0)
    assert total(b, FakeE.REL_X) == 20


def test_bad_tuning_values_fall_back_to_defaults():
    b = make_backend(env={"REMOTE_HID_SENSITIVITY": "fast", "REMOTE_HID_SCROLL_SCALE": "-3"})
    assert b._sensitivity == 1.0 and b._scroll_scale == 1.0


def test_hi_res_scroll_is_smooth_and_matches_legacy_notches():
    b = make_backend()
    for _ in range(40):
        b.scroll(0.1)  # 4 notches total, in tiny steps
    assert abs(total(b, FakeE.REL_WHEEL_HI_RES) - 480) <= 1
    assert total(b, FakeE.REL_WHEEL) in (3, 4)  # legacy axis only ticks per whole notch
    assert b._ui.syns >= 20  # many small events, not a few big jumps


def test_scroll_without_hi_res_falls_back_to_notches_without_losing_any():
    b = make_backend(FakeEOld)
    for _ in range(30):
        b.scroll(0.25)
    assert total(b, FakeE.REL_WHEEL) in (7, 8)
    assert all(c == FakeE.REL_WHEEL for c, _ in b._ui.events)


def test_scroll_direction_is_preserved():
    b = make_backend()
    for _ in range(20):
        b.scroll(-0.5)
    assert total(b, FakeE.REL_WHEEL_HI_RES) < 0 and total(b, FakeE.REL_WHEEL) < 0
