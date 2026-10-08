# Pre-login daemon (USB tethering)

`gui.py` and `client.py` are user apps — they only run once you've
logged in. This solves a different problem: a working keyboard/
trackpad **at the login screen itself**, when there's no session yet
and (per the original ask) no WiFi available either. `login_daemon.py`
is a systemd *system* service instead of something you launch, reusing
the same `protocol.py` / `handler.py` / `input_backend.py` as
everything else — only the "how does this start and how is it reached"
part is new.

## How it works

1. You enable **USB tethering** on the phone (Settings → Network &
   Internet → Hotspot & tethering → USB tethering — a separate toggle
   from USB debugging; debugging alone won't bring up a network
   interface with an address).
2. The daemon asks the OS directly: is there an interface that looks
   USB-attached (by name — systemd's predictable USB-port naming, or
   the older `usb0`/`rndis0` style) with a real IPv4 address, and what
   gateway does the OS believe it has. If nothing matches, it waits —
   this is what stops it from trying (and failing loudly, repeatedly)
   on a normal desk setup with no phone plugged in.
3. Once it finds one, it connects to `ws://<that gateway>:8765` — the
   phone app's normal server, unmodified — and feeds whatever it
   receives into `UinputBackend`, exactly like `client.py` does.

No changes needed on the Android side at all. The phone doesn't know
or care whether the connection came over WiFi or a USB-tethered link.

### Why this discovers the gateway instead of assuming one

The first version of this hardcoded `192.168.42.129` — Android's
commonly-documented USB tethering gateway, confirmed at the time
against multiple independent sources. Real testing on an actual device
then showed that scheme isn't reliable in practice: that phone's
tethering came up as a DHCP-assigned `10.98.4.0/24` address instead,
nothing like the hardcoded one. So the daemon now asks the OS what it
actually learned from the DHCP handshake, rather than assuming a fixed
value — see `login_daemon.py`'s own doc comment for the full account,
including a second real lesson from that same test (the live interface
reported state `UNKNOWN`, not `UP`, so the code checks for a real IPv4
address instead of trusting operational state).

## Security — read this before installing it

This is the first genuinely privileged, network-facing thing in this
project, and it's reachable *before login*, so it deserves a real
accounting of what is and isn't protected:

- **What's checked:** is there an interface that looks USB-attached by
  name, with a real IPv4 address and an OS-reported gateway. That's
  real, and it's unit tested (`tests/test_login_daemon.py`) against
  data shaped like an actual captured `ip -j addr`/`ip -j route`
  output, not synthetic examples.
- **What's NOT checked:** whether the thing answering at that gateway
  is actually *your* phone, versus any device that presents itself
  there once something tether-shaped exists. There's no pairing token
  or handshake yet — that would need matching changes on the Android
  side, and hasn't been built.
- **What that means in practice:** the real security boundary right
  now is physical access to this machine's USB-C port — the same
  boundary a literal wired keyboard has. Anyone who can plug something
  into that port could, in principle, present as a fake phone and
  inject input at your lock screen. If that's not an acceptable
  tradeoff for your environment, don't install this yet — say so and
  the pairing-token version is the right next thing to build, not this
  one as-is.
- **Why it doesn't run as root:** it only ever needs `/dev/uinput`
  access, so it runs as a dedicated unprivileged user instead of root,
  with systemd sandboxing (`ProtectSystem`, `ProtectHome`,
  `NoNewPrivileges`, etc. — see the `.service` file) limiting what it
  could do even if something did go wrong with it.

## Setup

Prerequisites: `uinput` module loaded and `python3-evdev` /
`python3-websockets` installed — same as the main README's Linux
client setup.

```bash
# 1. Dedicated system user (also creates a same-named group)
sudo useradd --system --no-create-home --shell /usr/sbin/nologin remote-hid

# 2. Code lives where the .service file's ExecStart expects it
sudo mkdir -p /opt/remote-hid
sudo cp -r linux-client /opt/remote-hid/

# 3. Grant that group access to /dev/uinput — a static rule, not the
#    TAG+="uaccess" one from the main README, which only applies to an
#    active logind session and there isn't one before login
sudo cp linux-client/systemd/99-remote-hid-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

# 4. Install and enable the service
sudo cp linux-client/systemd/remote-hid-login.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now remote-hid-login.service
```

## Testing it

```bash
# Watch it live
sudo systemctl status remote-hid-login.service
sudo journalctl -u remote-hid-login.service -f
```

Then: enable USB tethering on the phone with the cable connected, and
watch the journal for `[login-daemon] connected to ws://...`. To test
against the actual login screen rather than a running session: switch
to a text console (Ctrl+Alt+F3), confirm the service is active there
too (`systemctl status` doesn't need a graphical session), switch back
to the greeter (Ctrl+Alt+F1 or F2), and check whether the trackpad/
keyboard work there.

## What's unverified

Everything above the "Setup" heading is design and unit-tested logic.
The interface-discovery and message-relay logic are tested against
fakes shaped like real captured `ip -j` output (`tests/
test_login_daemon.py`); whether the whole chain actually works on a
real machine, with a real phone, at a real login screen, is only
knowable by trying it — there's no USB tethering hardware or way to
simulate it in the environment this was written in.
