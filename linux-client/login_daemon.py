"""System-level daemon for pre-login input: discovers a USB-tethered
phone's gateway address dynamically and connects to it, injecting
received input via uinput.

Runs as a systemd SYSTEM service (see systemd/remote-hid-login.service)
so it's alive before any login session exists. This is genuinely
different from gui.py/client.py: those are user apps you launch after
logging in; this exists specifically so a keyboard/trackpad works *at*
the login screen, when WiFi isn't available yet.

WHY THIS DISCOVERS THE GATEWAY INSTEAD OF ASSUMING ONE:
An earlier version of this file hardcoded 192.168.42.129 — Android's
commonly-documented USB tethering gateway address, confirmed against
multiple independent sources. Real testing on an actual device then
showed that documented scheme isn't reliable in practice: the phone
tested against used a DHCP-assigned 10.98.4.0/24 address instead,
nothing like the hardcoded one. So instead of assuming any fixed
address, this asks the OS directly: which interface looks like a
USB-attached device (by name — see _looks_like_usb_interface) and
actually has an IPv4 address, and what does the OS believe that
interface's gateway to be. That's asking the kernel to report what it
already learned from the DHCP handshake, rather than guessing at a
scheme.

Also learned from that same real output: don't filter on operstate
("UP" vs "UNKNOWN") — the real tethering interface reported UNKNOWN
despite working fine, same as an unrelated tailscale0 interface in
that same capture. Presence of a real IPv4 address is what's checked
instead.

SECURITY, read before deploying this:
What's checked: is there an interface that looks USB-attached by name,
with a real IPv4 address and an OS-reported gateway. What's NOT
checked: whether whatever answers at that gateway address is actually
*your* phone, versus any device presenting itself there once
something tether-shaped exists. There's no pairing token or handshake
yet — that would need matching changes on the Android side and isn't
built. The real security boundary right now is physical access to
this machine's USB-C port, same as a literal wired keyboard has. See
LOGIN_DAEMON.md for the full accounting before installing this.

This is the least end-to-end-testable code in this whole project — no
USB tethering hardware or way to simulate it exists in the environment
this was written in, and the interface-discovery logic changed based
on one real test's output rather than being verified fully. The
discovery and message-relay logic are unit tested against fakes
matching the real ip -j output schema; the real end-to-end behavior
can only be confirmed on an actual machine, at an actual login screen.
"""

import asyncio
import ipaddress
import json
import re
import subprocess

import websockets

from handler import handle_message
from input_backend import UinputBackend
from protocol import REPLACED_REASON, SessionReplaced

PORT = 8765
RETRY_SECONDS = 1

# A yanked USB cable does not close the TCP connection: the kernel just
# stops getting answers. With the old 600s ping_timeout the daemon sat on
# that dead socket for up to ten minutes and never looked at the NEW
# interface after a replug, which is exactly "sometimes works, sometimes
# doesn't" (works if the old session happened to die cleanly). Short
# keepalive on a local cable link is safe: a healthy link answers in ms.
PING_INTERVAL = 5
PING_TIMEOUT = 5

# How often the watcher re-asks the OS whether the cable's gateway is
# still the one we are connected to.
WATCH_SECONDS = 1

# Cable detection lives in netinfo.py (shared with the GUI). Re-exported under
# the old names so callers and tests keep working; `subprocess` stays imported
# here because the tests patch it through this module.
from netinfo import (  # noqa: E402,F401
    _candidate_interfaces,
    _default_gateway_for,
    _ipv4_address,
    find_tether_gateway,
    find_tether_gateways,
    looks_like_usb_name as _looks_like_usb_interface,
)


async def connect_and_relay(backend, uri: str) -> None:
    """One connection attempt: connects, relays messages into backend
    via the same tested handler.handle_message everything else uses,
    until the connection ends.
    """
    async with websockets.connect(
        uri,
        ping_interval=PING_INTERVAL,
        ping_timeout=PING_TIMEOUT,
        open_timeout=4,
        close_timeout=1,  # cancelling over a dead cable must not wait the 10s default
        compression=None,  # tiny frames: deflate only adds latency and CPU
    ) as ws:
        print(f"[login-daemon] connected to {uri}")
        async for raw_frame in ws:
            try:
                msg = json.loads(raw_frame)
            except json.JSONDecodeError:
                print(f"[login-daemon] dropping non-JSON frame: {raw_frame!r}")
                continue
            handle_message(msg, backend)
        print("[login-daemon] connection closed")
        if getattr(ws, "close_reason", None) == REPLACED_REASON:
            raise SessionReplaced(REPLACED_REASON)


def _tcp_peer_hex(ip: str, port: int) -> str:
    """How /proc/net/tcp writes a remote address: IPv4 bytes reversed, hex."""
    a, b, c, d = (int(x) for x in ip.split("."))
    return f"{d:02X}{c:02X}{b:02X}{a:02X}:{port:04X}"


def another_client_connected(gateway: str, port: int = PORT, proc_path: str = "/proc/net/tcp") -> bool:
    """True if some process on this machine already holds an ESTABLISHED
    connection to the phone. The daemon is a background fallback for the
    login screen: once the user's GUI client has the phone, the daemon
    must stay out of the way. The phone gives the newest connection the
    session, so a daemon that connected anyway would kick the GUI every
    time it retried. Called only while the daemon has no connection of its
    own, so any hit belongs to someone else. Reads the kernel table
    directly (no external tools); any error means "not busy", so a quirk
    here can never lock the login screen out.
    """
    try:
        want = _tcp_peer_hex(gateway, port)
        with open(proc_path) as f:
            next(f, None)  # header
            for line in f:
                fields = line.split()
                if len(fields) > 3 and fields[2] == want and fields[3] == "01":
                    return True
    except (OSError, ValueError):
        pass
    return False


async def _watch_gateway(gateway: str) -> None:
    """Returns as soon as the tether gateway is gone or changed (cable
    unplugged, or replugged and re-addressed). Used to cancel a relay
    that is stuck on a socket whose interface no longer exists.
    """
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(WATCH_SECONDS)
        current = await loop.run_in_executor(None, find_tether_gateway)
        if current != gateway:
            print(f"[login-daemon] tether gateway changed ({gateway} -> {current}), dropping session")
            return


async def relay_until_cable_changes(backend, gateway: str) -> None:
    """One session: relay until the connection ends OR the cable's
    gateway changes, whichever comes first. Whichever side finishes
    first, the other is cancelled so nothing is left dangling.
    """
    uri = f"ws://{gateway}:{PORT}"
    relay = asyncio.ensure_future(connect_and_relay(backend, uri))
    watcher = asyncio.ensure_future(_watch_gateway(gateway))
    try:
        await asyncio.wait({relay, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (relay, watcher):
            if not task.done():
                task.cancel()
        results = await asyncio.gather(relay, watcher, return_exceptions=True)
    # Surface a real connection error from the relay (not cancellation).
    exc = results[0]
    if isinstance(exc, Exception) and not isinstance(exc, asyncio.CancelledError):
        raise exc


async def run_forever() -> None:
    print("[login-daemon] starting — waiting for a USB-tethered phone")
    try:
        backend = UinputBackend()
    except Exception as exc:
        print(f"[login-daemon] could not start input backend: {exc}")
        return

    try:
        while True:
            gateway = find_tether_gateway()
            busy = False
            if gateway:
                busy = await asyncio.get_running_loop().run_in_executor(
                    None, another_client_connected, gateway
                )
            if gateway and not busy:
                try:
                    await relay_until_cable_changes(backend, gateway)
                except SessionReplaced:
                    print("[login-daemon] a user session took over the phone, standing by")
                except (OSError, websockets.exceptions.WebSocketException) as exc:
                    print(f"[login-daemon] connection attempt to ws://{gateway}:{PORT} failed: {exc}")
            await asyncio.sleep(RETRY_SECONDS)
    finally:
        backend.close()


def main() -> None:
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
