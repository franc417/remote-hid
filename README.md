# remote-hid

Turn an Android phone into a wireless trackpad and full keyboard for a
desktop, over the local network. No dongle, no cloud — the phone runs a
local server, the desktop runs a small client that injects the events as
real mouse/keyboard input.

See [`PROTOCOL.md`](./PROTOCOL.md) for the wire format between the two.

## Architecture

```
Android phone (server)              Desktop (client)
┌─────────────────────┐             ┌─────────────────────┐
│ Touch UI             │            │ Client app           │
│ (trackpad + keyboard)│  Wi-Fi     │ (receives events)    │
│                       │  LAN       │                      │
│ Local WebSocket       │──────────▶│ Input injection       │
│ server                │            │ (OS-level HID APIs)  │
└─────────────────────┘             └─────────────────────┘
```

The phone hosts the WebSocket server; the desktop client connects out to
it and translates incoming events into real input via OS APIs. On Linux
that's the kernel's `uinput` interface via `python-evdev`.

## Status

| Component      | Status                                              |
| --------------- | ---------------------------------------------------- |
| Protocol        | Defined, validated, unit tested on both sides         |
| Linux client    | Implemented — message handling fully tested; GUI app (`gui.py`) tested end-to-end including a caught-and-fixed cross-thread Tkinter bug; real `uinput` injection needs a real Linux box with permissions (see below) |
| Android server  | Embedded WebSocket server + protocol validation written, building via CI (see `android-app/`) — real device testing still ahead |
| Windows client  | Not started                                          |
| macOS client    | Not started                                          |

**Important honesty note:** what's tested so far is the message-parsing
and dispatch pipeline — decoded JSON in, the correct backend call out —
including a real end-to-end test over an actual WebSocket connection
(see `linux-client/tests/test_integration.py`). What is *not* tested yet
is real `uinput` device creation, because this was built in a sandboxed
container with no `/dev/uinput` and no real Android phone to pair with.
That part needs verification on your actual machine.

## Linux client

### Setup (Debian/Ubuntu/Mint)

```bash
sudo apt install python3-evdev python3-websockets python3-tk
```

`python3-tk` is only needed for the GUI app (`gui.py`) — skip it if
you're only ever going to use the `client.py` command-line form.

### Setup (Arch)

```bash
sudo pacman -S python-evdev python-websockets tk
```

### uinput permissions (all distros, systemd-based)

`evdev` needs to actually create a virtual input device at runtime,
which requires either running as root or being in a group with write
access to `/dev/uinput`. The cleanest way is a udev rule that grants the
active login session access automatically:

```bash
# load the module now, and on every boot from here on
sudo modprobe uinput
echo uinput | sudo tee /etc/modules-load.d/uinput.conf

# grant the logged-in session access to /dev/uinput
echo 'KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Log out and back in (or reboot) for the new permission to apply to your
session. Then confirm it actually works, independent of any network or
phone involvement, with:

```bash
cd linux-client
python3 smoke_test.py
```

If your cursor traces a small square on screen, `uinput` is working.

### Run — as an app

```bash
python3 gui.py
```

A small window: type the phone's `ws://<ip>:<port>` (shown on the
phone's screen once the Android app is running), hit Connect. It
remembers the address for next time, so after the first run you won't
need to type it again. `branding/generate-icons.sh
--install-desktop-icon` installs this as a real launcher entry in your
application menu, icon included.

### Run — as a command (for scripting/debugging)

```bash
cd linux-client
python3 client.py ws://<phone-ip>:<port>
```

### Test

```bash
cd linux-client
python3 -m pytest tests/ -v
```

GUI tests need a display — they skip automatically if there isn't one
(e.g. a bare CI box), and run for real on your actual desktop. To force
them headless: `xvfb-run -a python3 -m pytest tests/test_gui.py -v`
(needs the `xvfb` package).

## Roadmap

- [ ] Android server app (Kotlin): touch UI, embedded WebSocket server,
      NSD/mDNS advertisement, QR-code pairing
- [ ] Windows client (`SendInput` via `ctypes` or C#)
- [ ] macOS client (Quartz Event Services)
- [ ] Discovery: mDNS auto-connect + QR pairing on the client side
- [ ] TLS + pairing token for anything beyond a trusted home network

## License

MIT — see [`LICENSE`](./LICENSE).
