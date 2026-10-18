"""USB tether discovery: sysfs detection, odd interface names, no-default-route fallback."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import netinfo  # noqa: E402


def make_sysfs(tmp_path, name, subsystem=None, driver=None):
    """Builds /sys/class/net/<name>/device/{subsystem,driver} as symlinks like the kernel does."""
    dev = tmp_path / "sys" / "class" / "net" / name / "device"
    dev.mkdir(parents=True)
    if subsystem:
        target = tmp_path / "sys" / "bus" / subsystem
        target.mkdir(parents=True, exist_ok=True)
        (dev / "subsystem").symlink_to(target)
    if driver:
        target = tmp_path / "sys" / "drivers" / driver
        target.mkdir(parents=True, exist_ok=True)
        (dev / "driver").symlink_to(target)
    return str(tmp_path / "sys" / "class" / "net")


def addr(name, *ips):
    return {"ifname": name, "addr_info": [{"family": "inet", "local": ip, "prefixlen": 24} for ip in ips]}


def fake_ip(monkeypatch, addr_show=None, routes=None, neigh=None):
    """Patches subprocess.run so `ip -j addr/route/neigh` return canned JSON."""
    class R:
        def __init__(self, out): self.stdout = json.dumps(out)

    def run(cmd, **kw):
        joined = " ".join(cmd)
        if "addr show" in joined:
            return R(addr_show or [])
        if "route show dev" in joined:
            return R((routes or {}).get(cmd[-1], []))
        if "neigh show dev" in joined:
            return R((neigh or {}).get(cmd[-1], []))
        raise AssertionError(joined)

    monkeypatch.setattr(netinfo.subprocess, "run", run)


# ----------------------------------------------------------------- recognising USB

def test_sysfs_usb_bus_marks_an_oddly_named_interface_as_usb(tmp_path):
    root = make_sysfs(tmp_path, "eth1", subsystem="usb")
    assert netinfo.is_usb_netdev("eth1", root) is True


def test_sysfs_phone_driver_marks_it_as_usb_even_without_a_usb_subsystem_link(tmp_path):
    root = make_sysfs(tmp_path, "eth2", driver="rndis_host")
    assert netinfo.is_usb_netdev("eth2", root) is True


def test_a_pci_ethernet_card_is_not_usb(tmp_path):
    root = make_sysfs(tmp_path, "enp3s0", subsystem="pci", driver="r8169")
    assert netinfo.is_usb_netdev("enp3s0", root) is False


def test_missing_sysfs_means_not_usb_not_a_crash(tmp_path):
    assert netinfo.is_usb_netdev("nothing0", str(tmp_path)) is False


def test_mac_based_names_count_as_usb_by_name():
    assert netinfo.looks_like_usb_name("enxbe3af2b6059f")
    assert not netinfo.looks_like_usb_name("enxZZZ")
    assert not netinfo.looks_like_usb_name("eth0")


def test_an_interface_named_eth1_is_found_when_sysfs_says_usb(monkeypatch, tmp_path):
    root = make_sysfs(tmp_path, "eth1", subsystem="usb")
    fake_ip(monkeypatch, addr_show=[addr("lo", "127.0.0.1"), addr("eth1", "192.168.42.50"), addr("eth0", "10.0.0.2")])
    assert netinfo.usb_interfaces(root) == [{"name": "eth1", "ip": "192.168.42.50"}]


def test_wifi_vpn_and_container_interfaces_are_never_candidates(monkeypatch, tmp_path):
    fake_ip(monkeypatch, addr_show=[addr("wlan0", "10.0.0.2"), addr("tun0", "10.8.0.2"), addr("docker0", "172.17.0.1"),
                                    addr("tailscale0", "100.64.0.1")])
    assert netinfo.usb_interfaces(str(tmp_path)) == []


# ----------------------------------------------------------------- finding the phone

def test_gateway_comes_from_the_default_route(monkeypatch, tmp_path):
    fake_ip(monkeypatch,
            addr_show=[addr("enxbe3af2b6059f", "192.168.42.50")],
            routes={"enxbe3af2b6059f": [{"dst": "default", "gateway": "192.168.42.129"}]})
    assert netinfo.find_tether_gateways() == ["192.168.42.129"]


def test_no_default_route_falls_back_to_the_arp_neighbour(monkeypatch):
    fake_ip(monkeypatch,
            addr_show=[addr("enx0123456789ab", "192.168.210.17")],
            routes={"enx0123456789ab": [{"dst": "192.168.210.0/24"}]},
            neigh={"enx0123456789ab": [
                {"dst": "fe80::1", "state": ["STALE"]},
                {"dst": "192.168.210.1", "state": ["REACHABLE"]},
            ]})
    assert netinfo.find_tether_gateway() == "192.168.210.1"


def test_failed_and_foreign_neighbours_are_ignored(monkeypatch):
    fake_ip(monkeypatch,
            addr_show=[addr("enx0123456789ab", "192.168.210.17")],
            neigh={"enx0123456789ab": [
                {"dst": "192.168.210.1", "state": ["FAILED"]},
                {"dst": "10.1.1.1", "state": ["REACHABLE"]},
            ]})
    assert netinfo.find_tether_gateway() is None


def test_a_link_local_only_interface_is_still_waiting_for_dhcp_and_not_guessed_at(monkeypatch):
    fake_ip(monkeypatch,
            addr_show=[addr("enx0123456789ab", "169.254.12.9")],
            neigh={"enx0123456789ab": [{"dst": "169.254.12.1", "state": ["REACHABLE"]}]})
    assert netinfo.find_tether_gateway() is None


def test_ip_not_installed_is_handled(monkeypatch):
    def boom(*a, **k): raise FileNotFoundError("ip")
    monkeypatch.setattr(netinfo.subprocess, "run", boom)
    assert netinfo.find_tether_gateways() == [] and netinfo.scan_anchor_ips() == []


def test_two_phones_give_two_gateways_without_duplicates(monkeypatch):
    fake_ip(monkeypatch,
            addr_show=[addr("usb0", "192.168.42.50"), addr("enxaabbccddeeff", "192.168.7.2")],
            routes={"usb0": [{"dst": "default", "gateway": "192.168.42.129"}],
                    "enxaabbccddeeff": [{"dst": "default", "gateway": "192.168.42.129"}]})
    assert netinfo.find_tether_gateways() == ["192.168.42.129"]


# ----------------------------------------------------------------- scan anchors

def test_scan_anchors_cover_every_private_subnet_with_usb_first(monkeypatch, tmp_path):
    fake_ip(monkeypatch, addr_show=[
        addr("wlan0", "192.168.1.20"),
        addr("tun0", "10.8.0.2"),            # VPN: excluded
        addr("enp0s20f0u2", "192.168.42.50"),
        addr("eth0", "8.8.4.4"),             # public: not scanned
        addr("lo", "127.0.0.1"),
        addr("wlan1", "192.168.1.77"),       # same /24 as wlan0: one anchor
    ])
    anchors = netinfo.scan_anchor_ips()
    assert anchors[0] == "192.168.42.50"
    assert anchors == ["192.168.42.50", "192.168.1.20"]
