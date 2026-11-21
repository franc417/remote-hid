"""The cable check: what this computer sees of a phone on a USB cable, said in plain words, and the one fix that needs no root.

A phone with USB tethering on appears here as a network interface (driver rndis_host, cdc_ncm or cdc_ether). Three things must all be
true for the app to reach it: the interface exists; this computer has an address on it; and the phone's app answers on port 8765 at the
phone's address. This module looks at each in turn and names the first one that is not true. Everything that touches the system is
passed in, so it is tested without a phone.

    python3 cablecheck.py          print the report
    python3 cablecheck.py --fix    and, if the cable has no address, ask NetworkManager to bring it up
"""

import ipaddress
import os
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Optional

import netinfo
from reconnect import PHONE_PORT, _tcp_open


def _is_v4(text) -> bool:
    try:
        return ipaddress.ip_address(text).version == 4
    except ValueError:
        return False


def _driver(name: str, sys_root: str) -> str:
    try:
        return os.path.basename(os.path.realpath(os.path.join(sys_root, name, "device", "driver")))
    except OSError:
        return ""


def _neighbours(name: str, own: List[str], ip_json: Callable) -> List[str]:
    found = []
    for entry in ip_json("neigh", "show", "dev", name) or []:
        dst, state = entry.get("dst", ""), entry.get("state") or []
        state = [state] if isinstance(state, str) else list(state)
        if _is_v4(dst) and dst not in own and not ({"FAILED", "INCOMPLETE"} & set(state)):
            found.append(dst)
    return found


def cable_links(ip_json: Callable = netinfo._ip_json, sys_root: str = netinfo.SYS_NET) -> List[Dict]:
    """Every network interface that looks like a phone on a cable, whether or not it has an address yet."""
    links = []
    for iface in ip_json("addr", "show") or []:
        name = iface.get("ifname", "")
        if not name or any(name.startswith(prefix) for prefix in netinfo._EXCLUDED_PREFIXES):
            continue
        if not (netinfo.looks_like_usb_name(name) or netinfo.is_usb_netdev(name, sys_root)):
            continue
        ips = [a.get("local") for a in iface.get("addr_info", []) if _is_v4(a.get("local"))]
        gateway = None
        for route in ip_json("route", "show", "dev", name) or []:
            if route.get("dst") == "default" and route.get("gateway"):
                gateway = route["gateway"]
                break
        links.append({"name": name, "state": iface.get("operstate", "UNKNOWN"), "driver": _driver(name, sys_root), "ips": ips,
                      "gateway": gateway, "neighbours": _neighbours(name, ips, ip_json)})
    return links


def phone_candidates(link: Dict) -> List[str]:
    """Where the phone may be on this link: its default gateway, anything it has talked to, then where Android usually puts itself (.129 on
    older versions, .1 on newer ones)."""
    ips = [ip for ip in link["ips"] if not netinfo._is_link_local(ip)]
    if not ips:
        return []
    order = ([link["gateway"]] if link["gateway"] else []) + list(link["neighbours"])
    prefix = ".".join(ips[0].split(".")[:3])
    order += [f"{prefix}.129", f"{prefix}.1"]
    seen, out = set(ips), []
    for ip in order:
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def diagnose(ip_json: Callable = netinfo._ip_json, probe: Callable[[str, int, float], bool] = _tcp_open,
             sys_root: str = netinfo.SYS_NET, port: int = PHONE_PORT) -> Dict:
    """-> {"verdict": no_link | no_address | phone_silent | phone_found, "uri": ws://... or None, "links", "tried", "summary", "text"}"""
    links = cable_links(ip_json, sys_root)
    report: Dict = {"links": links, "uri": None, "tried": []}
    usable = [link for link in links if any(not netinfo._is_link_local(ip) for ip in link["ips"])]
    if not links:
        report["verdict"] = "no_link"
    elif not usable:
        report["verdict"] = "no_address"
    else:
        report["verdict"] = "phone_silent"
        for link in usable:
            for ip in phone_candidates(link):
                report["tried"].append(ip)
                if probe(ip, port, 0.8):
                    report["uri"], report["verdict"] = f"ws://{ip}:{port}", "phone_found"
                    break
            if report["uri"]:
                break
    report["summary"], report["text"] = format_report(report, port)
    return report


def format_report(report: Dict, port: int = PHONE_PORT):
    """-> (one line for the status bar, the full explanation)"""
    lines = ["Cable check", ""]
    for link in report["links"]:
        addr = ", ".join(link["ips"]) or "no address"
        lines.append(f"  {link['name']}: {link['state']}, driver {link['driver'] or '?'}, {addr}"
                     + (f", phone/gateway {link['gateway']}" if link["gateway"] else ""))
    if not report["links"]:
        lines.append("  (no network port from a phone cable)")
    lines.append("")
    verdict = report["verdict"]
    if verdict == "no_link":
        summary = "No cable found: this computer sees no network port from the phone."
        lines += [summary,
                  "On the phone: swipe down, tap the USB notification and choose 'USB tethering' (not 'File transfer' or 'Charging').",
                  "If it is already on: try another cable (a charge-only cable has no data wires) or another USB port.",
                  "In a terminal, `ip -br link` should show a new port (enx..., usb0 or enp...u...) the moment it works."]
    elif verdict == "no_address":
        name = report["links"][0]["name"]
        summary = f"The cable is there ({name}) but this computer has no address on it."
        lines += [summary,
                  "NetworkManager normally sets that up by itself (DHCP from the phone). The app can ask it to: press Check cable again,",
                  f"or run:  nmcli device connect {name}",
                  f"No NetworkManager?  sudo dhcpcd {name}   or   sudo dhclient {name}"]
    elif verdict == "phone_silent":
        guess = report["tried"][0] if report["tried"] else "the phone"
        summary = f"On the cable, but the phone's app does not answer at {guess}."
        lines += [summary, "Tried: " + ", ".join(report["tried"]) + f" (port {port}).",
                  "Open the Remote HID app on the phone: it should say 'Listening on ws://...:" + str(port) + " (USB cable)'.",
                  "If it shows another address, type that address into the address box here and press Connect.",
                  "Also check the phone is not blocking the app in battery saving (Settings > Apps > Remote HID > Battery > No restrictions)."]
    else:
        summary = f"Phone found on the cable: {report['uri']}"
        lines.append(summary)
    return summary, "\n".join(lines)


def try_fix(name: str, run: Callable = subprocess.run, which: Callable = shutil.which) -> str:
    """The one thing that needs no root: ask NetworkManager to bring the cable's port up (DHCP). -> what happened, in words."""
    nm = which("nmcli")
    if not nm:
        return f"NetworkManager (nmcli) is not installed, so nothing was changed. Configure {name} by DHCP, for example:  sudo dhcpcd {name}"
    try:
        state = ""
        for line in run([nm, "-t", "-f", "DEVICE,STATE", "device"], capture_output=True, text=True, timeout=10).stdout.splitlines():
            device, _, value = line.partition(":")
            if device == name:
                state = value
        if state.startswith("unmanaged"):
            run([nm, "device", "set", name, "managed", "yes"], capture_output=True, text=True, timeout=10)
        done = run([nm, "device", "connect", name], capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Could not ask NetworkManager: {exc}"
    if done.returncode == 0:
        return f"Asked NetworkManager to bring up {name} (it was '{state or 'unknown'}'): {(done.stdout or '').strip() or 'done'}"
    return f"NetworkManager could not bring up {name}: {((done.stderr or done.stdout) or '').strip()}. Try:  sudo dhcpcd {name}"


class CableOffer:
    """Decides when the app should connect to a phone on the cable by itself: once for each phone that shows up, and not again after the
    user pressed Disconnect, until the cable has been unplugged and plugged in again."""

    def __init__(self) -> None:
        self.offered: Optional[tuple] = None

    def update(self, reachable: List[str], connected: bool) -> Optional[str]:
        if not reachable:
            self.offered = None
            return None
        key = tuple(reachable)
        if key == self.offered:
            return None
        self.offered = key
        return None if connected else reachable[0]


def main(argv: List[str]) -> int:
    report = diagnose()
    print(report["text"])
    if "--fix" in argv and report["verdict"] == "no_address":
        print("\n" + try_fix(report["links"][0]["name"]))
    return 0 if report["verdict"] == "phone_found" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
