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

PORT = 8765
RETRY_SECONDS = 3

# Interfaces that are clearly not a tethered phone, excluded before
# even checking whether they look USB-attached.
_EXCLUDED_PREFIXES = ("lo", "docker", "virbr", "tailscale", "wl", "br-", "veth")


def _looks_like_usb_interface(name: str) -> bool:
    """USB-attached network interfaces get predictable names ending in
    u<N> (systemd's USB-port-path naming scheme — e.g. enp0s20f0u1,
    wwp0s20f0u2, both seen on real hardware), or the older usb0/rndis0
    style names.
    """
    return bool(re.search(r"u\d+$", name)) or name.startswith(("usb", "rndis"))


def _ipv4_address(iface: dict):
    """Returns this interface's IPv4 address if it has one — checked
    by parsing the address itself rather than trusting a "family" key
    to exist in every ip -j version, since that wasn't confirmed
    present in every example schema checked.
    """
    for addr in iface.get("addr_info", []):
        local = addr.get("local")
        if not local:
            continue
        try:
            if ipaddress.ip_address(local).version == 4:
                return local
        except ValueError:
            continue
    return None


def _candidate_interfaces():
    try:
        result = subprocess.run(
            ["ip", "-j", "addr", "show"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        interfaces = json.loads(result.stdout)
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    candidates = []
    for iface in interfaces:
        name = iface.get("ifname", "")
        if any(name.startswith(p) for p in _EXCLUDED_PREFIXES):
            continue
        if not _looks_like_usb_interface(name):
            continue
        if _ipv4_address(iface):
            candidates.append(name)
    return candidates


def _default_gateway_for(iface: str):
    try:
        result = subprocess.run(
            ["ip", "-j", "route", "show", "dev", iface],
            capture_output=True, text=True, timeout=5, check=True,
        )
        routes = json.loads(result.stdout)
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    for route in routes:
        if route.get("dst") == "default" and route.get("gateway"):
            return route["gateway"]
    return None


def find_tether_gateway():
    """Finds a USB-tethered phone's gateway address by asking the OS,
    not by assuming a fixed one. Returns None if nothing tether-shaped
    is currently up.
    """
    for iface in _candidate_interfaces():
        gateway = _default_gateway_for(iface)
        if gateway:
            return gateway
    return None


async def connect_and_relay(backend, uri: str) -> None:
    """One connection attempt: connects, relays messages into backend
    via the same tested handler.handle_message everything else uses,
    until the connection ends.
    """
    async with websockets.connect(uri, ping_interval=20, ping_timeout=600) as ws:
        print(f"[login-daemon] connected to {uri}")
        async for raw_frame in ws:
            try:
                msg = json.loads(raw_frame)
            except json.JSONDecodeError:
                print(f"[login-daemon] dropping non-JSON frame: {raw_frame!r}")
                continue
            handle_message(msg, backend)
        print("[login-daemon] connection closed")


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
            if gateway:
                uri = f"ws://{gateway}:{PORT}"
                try:
                    await connect_and_relay(backend, uri)
                except (OSError, websockets.exceptions.WebSocketException) as exc:
                    print(f"[login-daemon] connection attempt to {uri} failed: {exc}")
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
