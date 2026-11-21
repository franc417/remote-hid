"""Tests for the cable check (cablecheck.py): what the computer sees of a phone on a USB cable, in plain words. No phone, no root."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cablecheck as cc  # noqa: E402


def addr(name, *ips, state="UP"):
    return {"ifname": name, "operstate": state, "addr_info": [{"family": "inet", "local": ip} for ip in ips]}


def fake_ip(links, routes=None, neigh=None):
    def run(*args):
        if args[:2] == ("addr", "show"):
            return links
        if args[:3] == ("route", "show", "dev"):
            return (routes or {}).get(args[3], [])
        if args[:3] == ("neigh", "show", "dev"):
            return (neigh or {}).get(args[3], [])
        return None
    return run


def check(links, answers=(), routes=None, neigh=None, tmp="/nonexistent"):
    probed = []

    def probe(host, port, timeout):
        probed.append((host, port))
        return host in answers
    report = cc.diagnose(fake_ip(links, routes, neigh), probe, sys_root=tmp)
    return report, probed


def test_no_cable_says_how_to_turn_usb_tethering_on():
    report, probed = check([addr("lo", "127.0.0.1"), addr("wlp2s0", "192.168.0.105"), addr("docker0", "172.17.0.1"), addr("virbr0", "192.168.122.1"),
                            addr("tailscale0", "100.67.163.21")])
    assert report["verdict"] == "no_link" and probed == []
    assert "USB tethering" in report["text"] and "charge-only" in report["text"] and report["uri"] is None


def test_cable_without_an_address_names_the_port_and_the_fix():
    report, _ = check([addr("wlp2s0", "192.168.0.105"), addr("enx0a1b2c3d4e5f", state="DOWN")])
    assert report["verdict"] == "no_address"
    assert "enx0a1b2c3d4e5f" in report["summary"] and "nmcli device connect enx0a1b2c3d4e5f" in report["text"]
    report, _ = check([addr("enp0s20f0u2", "169.254.3.4")])                       # only a link-local address is no address either
    assert report["verdict"] == "no_address"


def test_phone_found_at_the_gateway_the_neighbour_or_the_usual_android_address():
    link = [addr("enp0s20f0u2", "192.168.42.17")]
    report, probed = check(link, answers={"192.168.42.129"}, routes={"enp0s20f0u2": [{"dst": "default", "gateway": "192.168.42.129"}]})
    assert report["verdict"] == "phone_found" and report["uri"] == "ws://192.168.42.129:8765" and probed[0] == ("192.168.42.129", 8765)
    assert "ws://192.168.42.129:8765" in report["summary"]
    report, probed = check(link, answers={"192.168.42.77"}, neigh={"enp0s20f0u2": [{"dst": "192.168.42.77", "state": ["REACHABLE"]},
                                                                               {"dst": "192.168.42.99", "state": ["FAILED"]}]})
    assert report["uri"] == "ws://192.168.42.77:8765" and ("192.168.42.99", 8765) not in probed
    report, _ = check(link, answers={"192.168.42.129"})                          # no route, no neighbour: the usual place
    assert report["uri"] == "ws://192.168.42.129:8765"
    report, _ = check([addr("usb0", "10.42.0.2")], answers={"10.42.0.1"})
    assert report["uri"] == "ws://10.42.0.1:8765"                                # the newer Android placement (.1)


def test_phone_that_does_not_answer_is_named_with_what_was_tried():
    report, probed = check([addr("enp0s20f0u2", "192.168.42.17")], routes={"enp0s20f0u2": [{"dst": "default", "gateway": "192.168.42.200"}]})
    assert report["verdict"] == "phone_silent" and report["uri"] is None
    assert [h for h, _ in probed][:3] == ["192.168.42.200", "192.168.42.129", "192.168.42.1"] and "192.168.42.17" not in report["tried"]
    assert "Listening on" in report["text"] and "8765" in report["text"] and "Battery" in report["text"]


def test_own_address_is_never_taken_for_the_phone():
    report, probed = check([addr("enp0s20f0u2", "192.168.42.129")], answers={"192.168.42.129"})       # this computer happens to hold .129
    assert ("192.168.42.129", 8765) not in probed


def test_fix_without_networkmanager_says_so():
    assert "not installed" in cc.try_fix("enx1", which=lambda _n: None) and "dhcpcd enx1" in cc.try_fix("enx1", which=lambda _n: None)


def runner(states, rc=0, out="Device 'enx1' successfully activated", err=""):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if argv[1:] == ["-t", "-f", "DEVICE,STATE", "device"]:
            return subprocess.CompletedProcess(argv, 0, states, "")
        return subprocess.CompletedProcess(argv, rc, out, err)
    return run, calls


def test_fix_asks_networkmanager_to_connect_and_to_manage_an_unmanaged_port():
    run, calls = runner("wlp2s0:connected\nenx1:disconnected\n")
    message = cc.try_fix("enx1", run=run, which=lambda _n: "/usr/bin/nmcli")
    assert ["/usr/bin/nmcli", "device", "connect", "enx1"] in calls and "successfully activated" in message and "disconnected" in message
    run, calls = runner("enx1:unmanaged\n")
    cc.try_fix("enx1", run=run, which=lambda _n: "/usr/bin/nmcli")
    assert calls.index(["/usr/bin/nmcli", "device", "set", "enx1", "managed", "yes"]) < calls.index(["/usr/bin/nmcli", "device", "connect", "enx1"])
    run, _ = runner("enx1:disconnected\n", rc=4, out="", err="Error: Connection activation failed")
    assert "activation failed" in cc.try_fix("enx1", run=run, which=lambda _n: "/usr/bin/nmcli")


def test_cable_offer_connects_once_per_phone_and_not_after_a_manual_disconnect():
    offer = cc.CableOffer()
    phone = ["ws://192.168.42.129:8765"]
    assert offer.update([], False) is None
    assert offer.update(phone, False) == phone[0]                    # a phone answers on the cable: connect to it
    assert offer.update(phone, False) is None                        # the user pressed Disconnect, the cable stays: leave it
    assert offer.update([], False) is None                           # unplugged ...
    assert offer.update(phone, False) == phone[0]                    # ... and plugged in again: offered again
    offer2 = cc.CableOffer()
    assert offer2.update(phone, True) is None and offer2.update(phone, False) is None      # already connected elsewhere: noted, not switched
