"""Desktop-side client: connects to the phone's WebSocket server and
feeds every message it receives into an InputBackend.
"""

import asyncio
import ipaddress
import json
import socket
import sys
from urllib.parse import urlparse

import websockets

from handler import handle_message
from protocol import REPLACED_REASON, SessionReplaced

# Dead-link detection. Pulling a USB cable or switching networks never
# closes the TCP connection, the kernel just stops hearing back, so the
# old 10 minute ping_timeout left the GUI stuck on a ghost session for
# that long. 10s + 15s notices within ~25s even if the phone is dozing
# (Wi-Fi power save can delay a pong by seconds, so this is deliberately
# not as tight as the cable-only login daemon). The route watcher below
# handles the common cases (cable pulled, Wi-Fi changed) in about 2s.
# The phone's read timeout (RemoteHidService.kt, 60s) must stay longer
# than PING_INTERVAL: these pings are the inbound traffic that keeps an
# idle but healthy connection alive.
PING_INTERVAL = 10
PING_TIMEOUT = 15
OPEN_TIMEOUT = 4    # a dead address must fail fast, not stall a whole retry round
CLOSE_TIMEOUT = 1   # closing over a dead link must not hang for the 10s default
ROUTE_CHECK_SECONDS = 1.5


def route_signature(host: str):
    """Which local address this machine would use to reach `host`, or None
    if there is no route at all. It changes when the cable is pulled (route
    gone -> None) or traffic moves to another interface (different source
    address), which is exactly when an existing connection is dead. UDP
    connect() sends nothing; it only asks the kernel for the route. Only
    literal IPs are checked (the phone is always addressed by IP); a
    hostname returns a constant so it can never cause a false drop."""
    try:
        ip = str(ipaddress.ip_address(host))
    except ValueError:
        return "n/a"
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(family, socket.SOCK_DGRAM)
    try:
        s.connect((ip, 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


async def _route_changed(host: str) -> None:
    """Returns when the route to `host` differs from what it was at start."""
    start = route_signature(host)
    while True:
        await asyncio.sleep(ROUTE_CHECK_SECONDS)
        if route_signature(host) != start:
            return


async def _read_loop(ws, backend, tag: str = "[client]") -> None:
    async for raw_frame in ws:
        try:
            msg = json.loads(raw_frame)
        except json.JSONDecodeError:
            print(f"{tag} dropping non-JSON frame: {raw_frame!r}")
            continue
        handle_message(msg, backend)


async def relay_session(ws, backend, host: str, tag: str = "[client]") -> None:
    """Relays until the connection ends or the network path to the phone
    changes. Raises SessionReplaced if the phone gave our session to a
    newer connection, ConnectionError if the path changed under us."""
    reader = asyncio.ensure_future(_read_loop(ws, backend, tag))
    watcher = asyncio.ensure_future(_route_changed(host))
    try:
        await asyncio.wait({reader, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (reader, watcher):
            if not task.done():
                task.cancel()
        results = await asyncio.gather(reader, watcher, return_exceptions=True)
    if reader.done() and not reader.cancelled():
        exc = results[0]
        if isinstance(exc, Exception):
            raise exc
        if getattr(ws, "close_reason", None) == REPLACED_REASON:
            raise SessionReplaced(REPLACED_REASON)
        return
    raise ConnectionError("network path to the phone changed")


async def run_client(uri: str, backend, on_status=None) -> None:
    host = urlparse(uri).hostname or ""
    async with websockets.connect(
        uri,
        ping_interval=PING_INTERVAL,
        ping_timeout=PING_TIMEOUT,
        open_timeout=OPEN_TIMEOUT,
        close_timeout=CLOSE_TIMEOUT,
    ) as ws:
        print(f"[client] connected to {uri}")
        if on_status:
            on_status(f"Connected to {uri}")
        try:
            await relay_session(ws, backend, host)
        except SessionReplaced:
            print("[client] another connection took over this phone")
            raise
        print("[client] connection closed")
        if on_status:
            on_status("Disconnected (connection closed)")


def main():
    if len(sys.argv) != 2:
        print("usage: python3 client.py ws://<phone-ip>:<port>")
        sys.exit(1)

    uri = sys.argv[1]

    try:
        from input_backend import UinputBackend
        backend = UinputBackend()
    except Exception as exc:
        # Missing evdev, no /dev/uinput, no permission, wrong platform, etc.
        print(f"[client] could not start the input backend: {exc}")
        print("[client] see README.md for uinput permission setup")
        sys.exit(1)

    try:
        asyncio.run(run_client(uri, backend))
    except KeyboardInterrupt:
        pass
    except SessionReplaced:
        print("[client] stopped: another connection took over this phone")
    finally:
        backend.close()


if __name__ == "__main__":
    main()
