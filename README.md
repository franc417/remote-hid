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
| Linux client    | Implemented — message handling fully tested; real `uinput` injection needs a real Linux box with permissions (see below) |
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

### Setup

```bash
cd linux-client
pip install -r requirements.txt
```

`python-evdev` needs to actually create a virtual input device at
runtime, which requires either running as root or being in a group with
write access to `/dev/uinput`. On systemd-based distros (Arch included)
the cleanest way is a udev rule that grants the active login session
access automatically:

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
python3 smoke_test.py
```

If your cursor traces a small square on screen, `uinput` is working.

### Run

```bash
python3 client.py ws://<phone-ip>:<port>
```

### Test

```bash
python3 -m pytest tests/ -v
```

## Roadmap

- [ ] Android server app (Kotlin): touch UI, embedded WebSocket server,
      NSD/mDNS advertisement, QR-code pairing
- [ ] Windows client (`SendInput` via `ctypes` or C#)
- [ ] macOS client (Quartz Event Services)
- [ ] Discovery: mDNS auto-connect + QR pairing on the client side
- [ ] TLS + pairing token for anything beyond a trusted home network

## License

MIT — see [`LICENSE`](./LICENSE).
