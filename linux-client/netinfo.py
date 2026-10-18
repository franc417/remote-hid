"""Finding a USB-tethered phone, shared by the login daemon and the GUI.

Why this exists as its own module: the daemon used to be the only code that
knew about cables, and it decided "this interface is USB" purely from its
NAME (…u<digit>, usb*, rndis*). Android tether interfaces also show up as
enx<mac> or plain eth1, which that check silently ignored, so a perfectly good
cable was "not there" on some machines and ports and fine on others. The GUI
knew nothing about cables at all (it only scanned the subnet of the default
route, after two failed rounds).

Detection order, most reliable first:
  1. sysfs: the interface's device sits on the USB bus (or uses a phone-class
     driver: rndis_host, cdc_ether, cdc_ncm, cdc_eem, ipheth). This does not
     depend on how the interface happens to be named.
  2. the old name patterns, kept as a fallback (and for machines where sysfs
     is not readable).

The phone's address is then taken from the default route on that interface,
or, when DHCP gave no default route, from the ARP neighbour on the link (the
phone is the only other host on a tether link).
"""

import ipaddress
import json
import os
import re
import subprocess
from typing import List, Optional

SYS_NET = "/sys/class/net"

# Drivers that mean "a phone (or similar) presenting a network port over USB".
PHONE_DRIVERS = {"rndis_host", "cdc_ether", "cdc_ncm", "cdc_eem", "ipheth"}

# Interfaces that are clearly not a tethered phone, excluded before even
# checking whether they look USB-attached.
_EXCLUDED_PREFIXES = ("lo", "docker", "virbr", "tailscale", "wl", "br-", "veth", "tun", "tap", "wg", "zt")

# For subnet scanning Wi-Fi is exactly what we DO want to cover (the usual
# case), so only the interfaces that are never a phone's network are skipped.
_SCAN_EXCLUDED_PREFIXES = tuple(p for p in _EXCLUDED_PREFIXES if p != "wl")


def looks_like_usb_name(name: str) -> bool:
    """USB-attached network interfaces get predictable names ending in
    u<N> (systemd's USB-port-path scheme, e.g. enp0s20f0u1, wwp0s20f0u2),
    enx<12 hex digits> (systemd's MAC-based name, common for tethering), or
    the older usb0/rndis0 style names.
    """
    return (
        bool(re.search(r"u\d+$", name))
        or bool(re.fullmatch(r"enx[0-9a-f]{12}", name))
        or name.startswith(("usb", "rndis"))
    )


def is_usb_netdev(name: str, sys_root: str = SYS_NET) -> bool:
    """True if sysfs says this interface is a USB network device, however it
    is named (eth1, enx…, anything). False when sysfs cannot tell."""
    device = os.path.join(sys_root, name, "device")
    try:
        if os.path.basename(os.path.realpath(os.path.join(device, "subsystem"))) == "usb":
            return True
        return os.path.basename(os.path.realpath(os.path.join(device, "driver"))) in PHONE_DRIVERS
    except OSError:
        return False


def _ipv4_address(iface: dict):
    """Returns this interface's IPv4 address if it has one, by parsing the
    address itself rather than trusting a "family" key to exist in every
    ip -j version."""
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


def _ip_json(*args: str):
    try:
        result = subprocess.run(
            ["ip", "-j", *args], capture_output=True, text=True, timeout=5, check=True,
        )
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError, OSError, KeyError):
        return None


def _is_link_local(ip: str) -> bool:
    return ip.startswith("169.254.")


def usb_interfaces(sys_root: str = SYS_NET) -> List[dict]:
    """USB network interfaces that have an IPv4 address, as
    [{"name": ..., "ip": ...}], in the order `ip` lists them."""
    interfaces = _ip_json("addr", "show")
    if not interfaces:
        return []
    found = []
    for iface in interfaces:
        name = iface.get("ifname", "")
        if any(name.startswith(p) for p in _EXCLUDED_PREFIXES):
            continue
        if not (looks_like_usb_name(name) or is_usb_netdev(name, sys_root)):
            continue
        ip = _ipv4_address(iface)
        if ip:
            found.append({"name": name, "ip": ip})
    return found


def _candidate_interfaces() -> List[str]:
    return [i["name"] for i in usb_interfaces()]


def _default_gateway_for(iface: str) -> Optional[str]:
    routes = _ip_json("route", "show", "dev", iface)
    for route in routes or []:
        if route.get("dst") == "default" and route.get("gateway"):
            return route["gateway"]
    return None


def _neighbor_gateway_for(iface: str, own_ip: str) -> Optional[str]:
    """The other host on the link, for when DHCP gave no default route. Uses
    the ARP table (the DHCP exchange itself fills it), restricted to an
    IPv4 neighbour that is not failed and shares our subnet's first three
    octets (tether links are /24)."""
    neighbors = _ip_json("neigh", "show", "dev", iface)
    prefix = ".".join(own_ip.split(".")[:3])
    for n in neighbors or []:
        dst = n.get("dst", "")
        state = n.get("state") or []
        if isinstance(state, str):
            state = [state]
        if dst.startswith(prefix + ".") and dst != own_ip and not {"FAILED", "INCOMPLETE"} & set(state):
            return dst
    return None


def find_tether_gateways() -> List[str]:
    """Every tethered phone's address, best first: default-route gateways,
    then neighbour-derived ones. Empty when nothing tether-shaped is up."""
    gateways: List[str] = []
    for iface in usb_interfaces():
        gw = _default_gateway_for(iface["name"])
        if not gw and not _is_link_local(iface["ip"]):
            gw = _neighbor_gateway_for(iface["name"], iface["ip"])
        if gw and gw not in gateways:
            gateways.append(gw)
    return gateways


def find_tether_gateway() -> Optional[str]:
    """Finds a USB-tethered phone's address by asking the OS, not by assuming
    a fixed one. None if nothing tether-shaped is currently up."""
    gateways = find_tether_gateways()
    return gateways[0] if gateways else None


def scan_anchor_ips(limit: int = 4) -> List[str]:
    """One private IPv4 address per /24 this machine is on, USB links first,
    for subnet scanning. The old scan only looked at the subnet of the
    default route (found by pretending to reach 8.8.8.8), which is the wrong
    one whenever a VPN or a second network owns that route."""
    interfaces = _ip_json("addr", "show") or []
    usb_names = {i["name"] for i in usb_interfaces()}
    ranked = []
    for iface in interfaces:
        name = iface.get("ifname", "")
        if any(name.startswith(p) for p in _SCAN_EXCLUDED_PREFIXES):
            continue
        for addr in iface.get("addr_info", []):
            local = addr.get("local")
            try:
                ip = ipaddress.ip_address(local) if local else None
            except ValueError:
                continue
            if ip is None or ip.version != 4 or not ip.is_private or ip.is_link_local or ip.is_loopback:
                continue
            ranked.append((0 if name in usb_names else 1, str(ip)))
    ranked.sort(key=lambda t: t[0])
    anchors, seen = [], set()
    for _, ip in ranked:
        net = ".".join(ip.split(".")[:3])
        if net not in seen:
            seen.add(net)
            anchors.append(ip)
    return anchors[:limit]
