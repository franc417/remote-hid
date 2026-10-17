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


def test_watch_gateway_returns_when_the_gateway_disappears(monkeypatch):
    monkeypatch.setattr(login_daemon, "WATCH_SECONDS", 0.02)
    answers = iter(["10.98.4.1", "10.98.4.1", None])
    monkeypatch.setattr(login_daemon, "find_tether_gateway", lambda: next(answers, None))
    asyncio.run(asyncio.wait_for(login_daemon._watch_gateway("10.98.4.1"), timeout=2))


def test_watch_gateway_returns_when_the_gateway_changes(monkeypatch):
    monkeypatch.setattr(login_daemon, "WATCH_SECONDS", 0.02)
    monkeypatch.setattr(login_daemon, "find_tether_gateway", lambda: "10.98.4.129")
    asyncio.run(asyncio.wait_for(login_daemon._watch_gateway("10.98.4.1"), timeout=2))


def test_session_stuck_on_a_dead_socket_is_dropped_when_cable_goes_away(monkeypatch):
    # The real bug: connect_and_relay hangs forever on a socket whose
    # interface vanished. The watcher must cancel it so the daemon can
    # look at the NEW interface after a replug.
    monkeypatch.setattr(login_daemon, "WATCH_SECONDS", 0.02)
    monkeypatch.setattr(login_daemon, "find_tether_gateway", lambda: None)
    cancelled = []

    async def hung_relay(backend, uri):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(uri)
            raise

    monkeypatch.setattr(login_daemon, "connect_and_relay", hung_relay)
    asyncio.run(asyncio.wait_for(
        login_daemon.relay_until_cable_changes(MockBackend(), "10.98.4.1"), timeout=2))
    assert cancelled == ["ws://10.98.4.1:8765"]


def test_relay_error_still_propagates_to_run_forever(monkeypatch):
    monkeypatch.setattr(login_daemon, "WATCH_SECONDS", 5)
    monkeypatch.setattr(login_daemon, "find_tether_gateway", lambda: "10.98.4.1")

    async def failing_relay(backend, uri):
        raise ConnectionRefusedError("phone app not running yet")

    monkeypatch.setattr(login_daemon, "connect_and_relay", failing_relay)
    try:
        asyncio.run(login_daemon.relay_until_cable_changes(MockBackend(), "10.98.4.1"))
        assert False, "expected the error to propagate"
    except ConnectionRefusedError:
        pass


def test_keepalive_is_short_enough_to_notice_an_unplugged_cable():
    assert login_daemon.PING_INTERVAL + login_daemon.PING_TIMEOUT <= 15


# ------------------------------------------------ standing aside for a user session

def test_tcp_peer_hex_matches_how_proc_net_tcp_writes_addresses():
    assert login_daemon._tcp_peer_hex("10.98.4.1", 8765) == "0104620A:223D"


_PROC_HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"


def _proc(tmp_path, *rows):
    path = tmp_path / "tcp"
    path.write_text(_PROC_HEADER + "".join(rows))
    return str(path)


def _row(rem, state):
    return f"   0: 0701620A:D2F4 {rem} {state} 00000000:00000000 00:00000000 00000000  1000        0 12345 1 0000 100 0 0 10 0\n"


def test_another_client_connected_sees_an_established_connection_to_the_phone(tmp_path):
    path = _proc(tmp_path, _row("0104620A:223D", "01"))
    assert login_daemon.another_client_connected("10.98.4.1", 8765, path) is True


def test_other_peers_and_non_established_states_do_not_count(tmp_path):
    path = _proc(tmp_path, _row("0104620A:223D", "06"),   # TIME_WAIT
                 _row("0A04620A:223D", "01"),             # a different host
                 _row("0104620A:1F90", "01"))             # a different port
    assert login_daemon.another_client_connected("10.98.4.1", 8765, path) is False


def test_an_unreadable_table_means_not_busy_so_the_login_screen_is_never_locked_out(tmp_path):
    assert login_daemon.another_client_connected("10.98.4.1", 8765, str(tmp_path / "missing")) is False


def test_another_client_connected_against_a_real_kernel_connection():
    import socket as _s
    srv = _s.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    cli = _s.create_connection(("127.0.0.1", port))
    conn, _ = srv.accept()
    try:
        assert login_daemon.another_client_connected("127.0.0.1", port) is True
    finally:
        cli.close(); conn.close(); srv.close()
    assert login_daemon.another_client_connected("127.0.0.1", port) is False


def test_connect_and_relay_reports_a_takeover_by_the_phone():
    import websockets
    from protocol import REPLACED_REASON, SessionReplaced

    async def phone(ws):
        await ws.close(code=1001, reason=REPLACED_REASON)

    async def scenario():
        async with websockets.serve(phone, "127.0.0.1", 8771):
            await asyncio.wait_for(
                login_daemon.connect_and_relay(MockBackend(), "ws://127.0.0.1:8771"), timeout=5)

    import pytest
    with pytest.raises(SessionReplaced):
        asyncio.run(scenario())


def _run_loop_briefly(seconds=0.3):
    async def go():
        task = asyncio.create_task(login_daemon.run_forever())
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(go())


def test_daemon_does_not_connect_while_a_user_session_holds_the_phone(monkeypatch):
    monkeypatch.setattr(login_daemon, "find_tether_gateway", lambda: "10.98.4.1")
    monkeypatch.setattr(login_daemon, "another_client_connected", lambda gw, *a: True)
    monkeypatch.setattr(login_daemon, "UinputBackend", MockBackend)
    monkeypatch.setattr(login_daemon, "RETRY_SECONDS", 0.05)
    attempted = []

    async def fake_relay(backend, gateway):
        attempted.append(gateway)

    monkeypatch.setattr(login_daemon, "relay_until_cable_changes", fake_relay)
    _run_loop_briefly()
    assert attempted == []


def test_daemon_survives_being_taken_over_and_keeps_looping(monkeypatch):
    from protocol import SessionReplaced
    monkeypatch.setattr(login_daemon, "find_tether_gateway", lambda: "10.98.4.1")
    monkeypatch.setattr(login_daemon, "another_client_connected", lambda gw, *a: False)
    monkeypatch.setattr(login_daemon, "UinputBackend", MockBackend)
    monkeypatch.setattr(login_daemon, "RETRY_SECONDS", 0.05)
    attempts = []

    async def fake_relay(backend, gateway):
        attempts.append(gateway)
        raise SessionReplaced("x")

    monkeypatch.setattr(login_daemon, "relay_until_cable_changes", fake_relay)
    _run_loop_briefly()
    assert len(attempts) >= 2  # it did not crash on the takeover
