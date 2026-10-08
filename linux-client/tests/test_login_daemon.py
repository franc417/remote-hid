import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import login_daemon
from input_backend import MockBackend


class _FakeCompletedProcess:
    def __init__(self, stdout):
        self.stdout = stdout


def _fake_run(outputs):
    """Returns a stand-in for subprocess.run that returns the next
    canned output each call, keyed by matching a substring of the
    command — close enough to the real ["ip", "-j", ...] calls without
    needing to match argv exactly.
    """

    def run(cmd, **kwargs):
        key = " ".join(cmd)
        for match, stdout in outputs.items():
            if match in key:
                return _FakeCompletedProcess(json.dumps(stdout))
        raise AssertionError(f"unexpected command: {cmd}")

    return run


# Real addr_info shape seen from an actual "ip -j addr show" capture,
# trimmed to the fields this code reads.
REAL_ADDR_SHOW = [
    {"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
    {"ifname": "wwp0s20f0u2", "addr_info": []},
    {"ifname": "enp0s31f6", "addr_info": []},
    {
        "ifname": "wlp4s0",
        "addr_info": [{"local": "192.168.0.105", "prefixlen": 24}],
    },
    {
        "ifname": "tailscale0",
        "addr_info": [{"local": "100.67.163.21", "prefixlen": 32}],
    },
    {
        "ifname": "virbr0",
        "addr_info": [{"local": "192.168.122.1", "prefixlen": 24}],
    },
    {
        "ifname": "docker0",
        "addr_info": [{"local": "172.17.0.1", "prefixlen": 16}],
    },
    {
        # The one that actually matters: real USB tethering, DHCP
        # assigned — not the commonly-documented 192.168.42.x scheme.
        "ifname": "enp0s20f0u1",
        "addr_info": [{"local": "10.98.4.108", "prefixlen": 24}],
    },
]

REAL_ROUTE_SHOW = [
    {"dst": "default", "gateway": "10.98.4.1", "dev": "enp0s20f0u1", "metric": 600},
    {"dst": "10.98.4.0/24", "dev": "enp0s20f0u1", "protocol": "kernel"},
]


def test_looks_like_usb_interface_matches_real_names_seen_on_hardware():
    assert login_daemon._looks_like_usb_interface("enp0s20f0u1") is True
    assert login_daemon._looks_like_usb_interface("wwp0s20f0u2") is True
    assert login_daemon._looks_like_usb_interface("usb0") is True
    assert login_daemon._looks_like_usb_interface("rndis0") is True


def test_looks_like_usb_interface_rejects_non_usb_names():
    assert login_daemon._looks_like_usb_interface("wlp4s0") is False
    assert login_daemon._looks_like_usb_interface("enp0s31f6") is False
    assert login_daemon._looks_like_usb_interface("eth0") is False


def test_ipv4_address_finds_v4_and_ignores_v6():
    iface = {
        "addr_info": [
            {"local": "fe80::1", "prefixlen": 64},
            {"local": "10.98.4.108", "prefixlen": 24},
        ]
    }
    assert login_daemon._ipv4_address(iface) == "10.98.4.108"


def test_ipv4_address_returns_none_with_no_addresses():
    assert login_daemon._ipv4_address({"addr_info": []}) is None


def test_candidate_interfaces_finds_the_real_tether_interface_and_excludes_the_rest(monkeypatch):
    monkeypatch.setattr(
        login_daemon.subprocess, "run", _fake_run({"addr show": REAL_ADDR_SHOW})
    )
    # Exactly the real tethering interface — not wifi, not docker/
    # virbr/tailscale, not the empty wwp*/onboard-ethernet entries.
    assert login_daemon._candidate_interfaces() == ["enp0s20f0u1"]


def test_default_gateway_for_reads_the_real_gateway(monkeypatch):
    monkeypatch.setattr(
        login_daemon.subprocess,
        "run",
        _fake_run({"route show dev enp0s20f0u1": REAL_ROUTE_SHOW}),
    )
    assert login_daemon._default_gateway_for("enp0s20f0u1") == "10.98.4.1"


def test_default_gateway_for_returns_none_when_no_default_route(monkeypatch):
    monkeypatch.setattr(
        login_daemon.subprocess,
        "run",
        _fake_run({"route show dev enp0s20f0u1": [{"dst": "10.98.4.0/24", "dev": "enp0s20f0u1"}]}),
    )
    assert login_daemon._default_gateway_for("enp0s20f0u1") is None


def test_find_tether_gateway_end_to_end_against_the_real_captured_output(monkeypatch):
    monkeypatch.setattr(
        login_daemon.subprocess,
        "run",
        _fake_run(
            {
                "addr show": REAL_ADDR_SHOW,
                "route show dev enp0s20f0u1": REAL_ROUTE_SHOW,
            }
        ),
    )
    assert login_daemon.find_tether_gateway() == "10.98.4.1"


def test_find_tether_gateway_returns_none_with_no_tethering(monkeypatch):
    # Same capture, minus the tethering interface — e.g. before
    # plugging in or enabling tethering.
    no_tether = [iface for iface in REAL_ADDR_SHOW if iface["ifname"] != "enp0s20f0u1"]
    monkeypatch.setattr(login_daemon.subprocess, "run", _fake_run({"addr show": no_tether}))
    assert login_daemon.find_tether_gateway() is None


def test_subprocess_failure_is_handled_gracefully(monkeypatch):
    def raise_missing(cmd, **kwargs):
        raise FileNotFoundError("ip: command not found")

    monkeypatch.setattr(login_daemon.subprocess, "run", raise_missing)
    assert login_daemon._candidate_interfaces() == []
    assert login_daemon.find_tether_gateway() is None


def test_connect_and_relay_processes_messages_end_to_end():
    # Same fake-local-server pattern as test_integration.py — proves
    # the relay path (websocket -> json.loads -> handle_message ->
    # backend) works, independent of the untestable part (real
    # interface discovery on real hardware).
    import websockets

    messages = [
        {"t": "move", "dx": 4, "dy": -2},
        {"t": "key", "code": "KeyA", "action": "down", "mods": []},
    ]

    async def fake_phone_server(websocket):
        for msg in messages:
            await websocket.send(json.dumps(msg))
        await websocket.close()

    async def scenario():
        backend = MockBackend()
        async with websockets.serve(fake_phone_server, "127.0.0.1", 8770):
            await asyncio.wait_for(
                login_daemon.connect_and_relay(backend, "ws://127.0.0.1:8770"), timeout=5
            )
        return backend

    backend = asyncio.run(scenario())
    assert backend.calls == [
        ("move", 4, -2),
        ("key", "KeyA", "down", ()),
    ]


def test_run_forever_skips_connecting_when_nothing_tether_shaped_is_up(monkeypatch):
    monkeypatch.setattr(login_daemon, "find_tether_gateway", lambda: None)
    monkeypatch.setattr(login_daemon, "UinputBackend", MockBackend)

    attempted = []

    async def fake_connect_and_relay(backend, uri):
        attempted.append(uri)

    monkeypatch.setattr(login_daemon, "connect_and_relay", fake_connect_and_relay)
    monkeypatch.setattr(login_daemon, "RETRY_SECONDS", 0.05)

    async def run_briefly():
        task = asyncio.create_task(login_daemon.run_forever())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_briefly())
    assert attempted == []
