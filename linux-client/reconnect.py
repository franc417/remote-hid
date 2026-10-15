"""Remembered phones + auto-reconnect policy for the desktop client.

Kept free of Tkinter and of any real network use beyond the injectable
`probe`, so the policy -- which phone to try, in what order, how long to
wait -- is testable on its own. gui.py wires it to the actual connection.

Why a subnet fallback exists: the phone's address is a DHCP lease, so a
remembered ws://192.168.1.23:8765 goes stale whenever the router hands the
phone a different one. Re-scanning the local /24 for the phone's port is
what turns "reconnect to a known phone" into something that keeps working
after that, without re-scanning a QR code each time.
"""

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional

CONFIG_DIR = Path.home() / ".config" / "remote-hid"
KNOWN_PATH = CONFIG_DIR / "known_devices.json"
LEGACY_PATH = CONFIG_DIR / "last_connection.json"  # single-URI file older versions wrote
PHONE_PORT = 8765
MAX_KNOWN = 10
# Failed rounds of known addresses before also scanning the subnet. One
# retry first: a phone that just woke from sleep often needs a second try,
# and a scan is noisy compared to retrying an address that is probably right.
SCAN_AFTER_ATTEMPTS = 2


def load_known(path: Path = KNOWN_PATH, legacy: Path = LEGACY_PATH) -> List[str]:
    """Remembered phone URIs, most recently connected first. Falls back to
    the old single-address file so an upgrade doesn't forget the last phone."""
    try:
        data = json.loads(path.read_text())
        uris = [u for u in data.get("uris", []) if isinstance(u, str) and u]
        if uris:
            return uris[:MAX_KNOWN]
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        pass
    try:
        old = json.loads(legacy.read_text()).get("uri", "")
        return [old] if old else []
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return []


def remember(uri: str, path: Path = KNOWN_PATH, legacy: Path = LEGACY_PATH) -> None:
    """Record a phone that actually connected: moves it to the front, keeps
    the list short. Only call this on a real connection -- remembering an
    address that never worked would put a dead one first on every retry."""
    uris = [u for u in load_known(path, legacy) if u != uri]
    uris.insert(0, uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"uris": uris[:MAX_KNOWN]}))


def backoff_delay(attempt: int) -> float:
    """Seconds to wait after the Nth consecutive failed round (0-based):
    1, 2, 4, 8, then a steady 15. Short at first because most drops are a
    phone briefly asleep; capped so a phone that comes back is noticed fast."""
    return float(min(15, 2 ** max(0, attempt)))


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def subnet_hosts(own_ip: str) -> List[str]:
    """Every other address in own_ip's /24. Assumes a /24, the overwhelmingly
    common home/hotspot/USB-tether size; on a wider network this just finds
    fewer phones (never a wrong one), it can't misdirect a connection."""
    parts = own_ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return []
    prefix = ".".join(parts[:3])
    return [f"{prefix}.{n}" for n in range(1, 255) if f"{prefix}.{n}" != own_ip]


def scan_subnet(
    own_ip: str,
    port: int = PHONE_PORT,
    timeout: float = 0.3,
    probe: Callable[[str, int, float], bool] = _tcp_open,
    workers: int = 64,
) -> List[str]:
    """ws:// URIs of hosts on own_ip's /24 with `port` open. Only says the
    port is open -- the WebSocket handshake that follows is what confirms
    it's really the phone app, so a different service on 8765 just fails there."""
    hosts = subnet_hosts(own_ip)
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        hits = list(pool.map(lambda h: probe(h, port, timeout), hosts))
    return [f"ws://{h}:{port}" for h, ok in zip(hosts, hits) if ok]


def candidates(
    primary: Optional[str],
    known: List[str],
    attempt: int,
    scan: Optional[Callable[[], List[str]]] = None,
) -> List[str]:
    """Addresses to try this round, best first, no duplicates: what's in the
    address box (the user's explicit choice), then remembered phones by
    recency, and -- only after SCAN_AFTER_ATTEMPTS failed rounds -- whatever
    the subnet scan finds, so a phone whose address changed is still found."""
    order: List[str] = []
    for uri in ([primary] if primary else []) + list(known):
        if uri and uri not in order:
            order.append(uri)
    if scan is not None and attempt >= SCAN_AFTER_ATTEMPTS:
        for uri in scan():
            if uri not in order:
                order.append(uri)
    return order
