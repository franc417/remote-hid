"""Stale-session handling in client.py: dead links, route changes, takeover."""

import asyncio
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import client  # noqa: E402
from input_backend import MockBackend  # noqa: E402
from protocol import REPLACED_REASON, SessionReplaced  # noqa: E402

websockets = pytest.importorskip("websockets")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_route_signature_for_loopback_and_hostnames():
    assert client.route_signature("127.0.0.1") == "127.0.0.1"
    assert client.route_signature("phone.local") == "n/a"  # never a false drop on a hostname


def test_route_signature_is_none_when_there_is_no_route(monkeypatch):
    class NoRoute:
        def __init__(self, *a): pass
        def connect(self, addr): raise OSError("Network is unreachable")
        def close(self): pass

    monkeypatch.setattr(client.socket, "socket", NoRoute)
    assert client.route_signature("10.98.4.1") is None


def test_route_changed_fires_when_the_source_address_changes(monkeypatch):
    monkeypatch.setattr(client, "ROUTE_CHECK_SECONDS", 0.02)
    answers = iter(["10.98.4.7", "10.98.4.7", "192.168.1.9"])
    monkeypatch.setattr(client, "route_signature", lambda host: next(answers, "192.168.1.9"))
    asyncio.run(asyncio.wait_for(client._route_changed("10.98.4.1"), timeout=2))


def test_route_changed_fires_when_the_route_disappears(monkeypatch):
    monkeypatch.setattr(client, "ROUTE_CHECK_SECONDS", 0.02)
    answers = iter(["10.98.4.7", None])
    monkeypatch.setattr(client, "route_signature", lambda host: next(answers, None))
    asyncio.run(asyncio.wait_for(client._route_changed("10.98.4.1"), timeout=2))


def test_session_replaced_is_raised_when_the_phone_hands_the_session_over():
    port = _free_port()

    async def phone(ws):
        await ws.close(code=1001, reason=REPLACED_REASON)

    async def scenario():
        async with websockets.serve(phone, "127.0.0.1", port):
            await asyncio.wait_for(client.run_client(f"ws://127.0.0.1:{port}", MockBackend()), timeout=5)

    with pytest.raises(SessionReplaced):
        asyncio.run(scenario())


def test_an_ordinary_close_is_not_mistaken_for_a_takeover():
    port = _free_port()
    seen = []

    async def phone(ws):
        await ws.close(code=1000, reason="bye")

    async def scenario():
        async with websockets.serve(phone, "127.0.0.1", port):
            await asyncio.wait_for(
                client.run_client(f"ws://127.0.0.1:{port}", MockBackend(), on_status=seen.append), timeout=5)

    asyncio.run(scenario())
    assert seen[-1].startswith("Disconnected")


def test_a_route_change_drops_a_session_that_looks_healthy(monkeypatch):
    # The cable-pull / network-switch case: the socket is still "open" as far as
    # the kernel is concerned, so only the route watcher can notice.
    port = _free_port()
    monkeypatch.setattr(client, "ROUTE_CHECK_SECONDS", 0.05)
    calls = {"n": 0}

    def sig(host):
        calls["n"] += 1
        return "A" if calls["n"] < 3 else "B"

    monkeypatch.setattr(client, "route_signature", sig)

    async def phone(ws):
        await ws.wait_closed()

    async def scenario():
        async with websockets.serve(phone, "127.0.0.1", port):
            await asyncio.wait_for(client.run_client(f"ws://127.0.0.1:{port}", MockBackend()), timeout=5)

    with pytest.raises(ConnectionError):
        asyncio.run(scenario())


def test_a_black_hole_address_fails_fast_instead_of_stalling_the_retry_round(monkeypatch):
    # Listening socket that never answers the WebSocket handshake.
    monkeypatch.setattr(client, "OPEN_TIMEOUT", 0.3)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        async def scenario():
            await asyncio.wait_for(client.run_client(f"ws://127.0.0.1:{port}", MockBackend()), timeout=5)

        with pytest.raises((TimeoutError, asyncio.TimeoutError, OSError)):
            asyncio.run(scenario())
    finally:
        srv.close()


def test_keepalive_notices_a_dead_link_in_well_under_a_minute():
    # Was 20s + 600s: a pulled cable left a ghost session for ten minutes.
    assert client.PING_INTERVAL + client.PING_TIMEOUT <= 30
    assert client.PING_INTERVAL < 60  # the phone's read timeout (60s) must outlast the ping cadence
