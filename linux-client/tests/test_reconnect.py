import json
import socket

import reconnect


def paths(tmp_path):
    return tmp_path / "known.json", tmp_path / "last_connection.json"


def test_remember_puts_newest_first_and_dedupes(tmp_path):
    known, legacy = paths(tmp_path)
    reconnect.remember("ws://10.0.0.5:8765", known, legacy)
    reconnect.remember("ws://10.0.0.6:8765", known, legacy)
    reconnect.remember("ws://10.0.0.5:8765", known, legacy)  # reconnecting to the first again
    assert reconnect.load_known(known, legacy) == ["ws://10.0.0.5:8765", "ws://10.0.0.6:8765"]


def test_known_list_is_capped(tmp_path):
    known, legacy = paths(tmp_path)
    for n in range(reconnect.MAX_KNOWN + 5):
        reconnect.remember(f"ws://10.0.0.{n}:8765", known, legacy)
    got = reconnect.load_known(known, legacy)
    assert len(got) == reconnect.MAX_KNOWN
    assert got[0] == f"ws://10.0.0.{reconnect.MAX_KNOWN + 4}:8765"  # newest kept


def test_upgrade_does_not_forget_the_old_single_address(tmp_path):
    known, legacy = paths(tmp_path)
    legacy.write_text(json.dumps({"uri": "ws://192.168.1.9:8765"}))
    assert reconnect.load_known(known, legacy) == ["ws://192.168.1.9:8765"]
    reconnect.remember("ws://192.168.1.10:8765", known, legacy)  # old one is carried along, not dropped
    assert reconnect.load_known(known, legacy) == ["ws://192.168.1.10:8765", "ws://192.168.1.9:8765"]


def test_corrupt_or_missing_files_mean_nothing_remembered(tmp_path):
    known, legacy = paths(tmp_path)
    assert reconnect.load_known(known, legacy) == []
    known.write_text("{not json")
    legacy.write_text("[]")
    assert reconnect.load_known(known, legacy) == []


def test_backoff_grows_then_caps():
    assert [reconnect.backoff_delay(n) for n in range(7)] == [1, 2, 4, 8, 15, 15, 15]
    assert reconnect.backoff_delay(-3) == 1  # never negative or zero


def test_subnet_hosts_is_the_rest_of_the_slash_24():
    hosts = reconnect.subnet_hosts("192.168.43.7")
    assert len(hosts) == 253
    assert "192.168.43.7" not in hosts
    assert "192.168.43.1" in hosts and "192.168.43.254" in hosts
    assert reconnect.subnet_hosts("not-an-ip") == []
    assert reconnect.subnet_hosts("127.0.0") == []


def test_scan_subnet_returns_only_hosts_with_the_port_open():
    open_hosts = {"10.1.2.30", "10.1.2.99"}
    got = reconnect.scan_subnet("10.1.2.5", probe=lambda h, p, t: h in open_hosts)
    assert sorted(got) == ["ws://10.1.2.30:8765", "ws://10.1.2.99:8765"]


def test_tcp_probe_against_a_real_listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)  # the kernel completes the handshake into the backlog; no accept() needed
    port = srv.getsockname()[1]
    try:
        assert reconnect._tcp_open("127.0.0.1", port, 1.0) is True
    finally:
        srv.close()
    assert reconnect._tcp_open("127.0.0.1", port, 0.3) is False  # closed again


def test_candidates_order_and_dedupe():
    known = ["ws://a:8765", "ws://b:8765"]
    assert reconnect.candidates("ws://b:8765", known, 0) == ["ws://b:8765", "ws://a:8765"]
    assert reconnect.candidates("", known, 0) == known
    assert reconnect.candidates(None, [], 0) == []


def test_scan_only_kicks_in_after_enough_failed_rounds():
    scans = []

    def scan():
        scans.append(1)
        return ["ws://new:8765", "ws://a:8765"]

    known = ["ws://a:8765"]
    assert reconnect.candidates(None, known, 0, scan) == known
    assert reconnect.candidates(None, known, reconnect.SCAN_AFTER_ATTEMPTS - 1, scan) == known
    assert scans == []  # not even called early: a scan is noisy
    assert reconnect.candidates(None, known, reconnect.SCAN_AFTER_ATTEMPTS, scan) == ["ws://a:8765", "ws://new:8765"]
    assert scans == [1]


def test_prioritize_puts_live_addresses_first_and_keeps_dead_ones_last():
    live = {"192.168.1.9"}
    probe = lambda host, port, timeout: host in live
    out = reconnect.prioritize(
        ["ws://10.98.4.1:8765", "ws://192.168.1.9:8765", "ws://192.168.1.4:8765"], probe=probe)
    assert out == ["ws://192.168.1.9:8765", "ws://10.98.4.1:8765", "ws://192.168.1.4:8765"]


def test_prioritize_keeps_order_within_each_group_and_handles_tiny_inputs():
    probe = lambda host, port, timeout: True
    assert reconnect.prioritize(["ws://a:1", "ws://b:2"], probe=probe) == ["ws://a:1", "ws://b:2"]
    assert reconnect.prioritize([], probe=probe) == []
    assert reconnect.prioritize(["ws://a:1"], probe=probe) == ["ws://a:1"]


def test_a_cable_phone_comes_after_the_typed_address_and_before_remembered_ones():
    out = reconnect.candidates("ws://typed:8765", ["ws://old:8765"], 0, tether=["ws://192.168.42.129:8765"])
    assert out == ["ws://typed:8765", "ws://192.168.42.129:8765", "ws://old:8765"]


def test_a_cable_phone_already_remembered_is_not_listed_twice():
    out = reconnect.candidates(None, ["ws://192.168.42.129:8765", "ws://old:8765"], 0, tether=["ws://192.168.42.129:8765"])
    assert out == ["ws://192.168.42.129:8765", "ws://old:8765"]


def test_filter_reachable_keeps_only_answering_targets_in_order():
    live = {"192.168.1.9", "192.168.42.129"}
    probe = lambda host, port, timeout: host in live
    out = reconnect.filter_reachable(
        ["ws://10.0.0.1:8765", "ws://192.168.42.129:8765", "ws://192.168.1.4:8765", "ws://192.168.1.9:8765"], probe=probe)
    assert out == ["ws://192.168.42.129:8765", "ws://192.168.1.9:8765"]


def test_filter_reachable_handles_empty_and_all_dead():
    probe = lambda host, port, timeout: False
    assert reconnect.filter_reachable([], probe=probe) == []
    assert reconnect.filter_reachable(["ws://a:1"], probe=probe) == []
