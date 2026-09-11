"""Standalone check that uinput input injection actually works on this
machine — independent of the network/phone side entirely. Run this
after setting up /dev/uinput permissions (see ../README.md) and before
trying to connect to the phone, so you know which half of the system
you're debugging if something's wrong.
"""

import sys
import time


def main():
    try:
        from evdev import UInput, ecodes as e
    except ImportError:
        print("evdev not installed — on Arch: sudo pacman -S python-evdev")
        sys.exit(1)

    print("Creating a virtual input device...")
    try:
        # A button capability (EV_KEY) has to be declared alongside the
        # motion axes, even though this test never presses one — without
        # it, udev/libinput won't classify the device as a mouse at all,
        # and relative-motion events get silently dropped rather than
        # moving the cursor. This bit us on the first run.
        capabilities = {
            e.EV_REL: [e.REL_X, e.REL_Y],
            e.EV_KEY: [e.BTN_LEFT],
        }
        ui = UInput(capabilities, name="remote-hid-smoke-test")
    except Exception as exc:
        print(f"Could not create the device: {exc}")
        print("Usually means /dev/uinput permissions aren't set up yet — see ../README.md")
        sys.exit(1)

    print("Device created. Tracing a small square with the cursor in 2 seconds...")
    print("(watch your mouse cursor)")
    time.sleep(2)

    moves = [(40, 0)] * 10 + [(0, 40)] * 10 + [(-40, 0)] * 10 + [(0, -40)] * 10
    for dx, dy in moves:
        ui.write(e.EV_REL, e.REL_X, dx)
        ui.write(e.EV_REL, e.REL_Y, dy)
        ui.syn()
        time.sleep(0.02)

    ui.close()
    print("Done. If your cursor traced a small square, uinput is working correctly.")


if __name__ == "__main__":
    main()
