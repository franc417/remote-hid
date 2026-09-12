"""Tests for the Tkinter GUI wrapper (gui.py). These need a real or
virtual display — skipped automatically if tkinter can't open a window,
so this doesn't break on headless machines without Xvfb. On your actual
desktop (Mint or otherwise), these run for real against a real display.

Run with: python3 -m pytest tests/test_gui.py -v
Headless: xvfb-run -a python3 -m pytest tests/test_gui.py -v
"""

import asyncio
import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tk = pytest.importorskip("tkinter")

try:
    _probe = tk.Tk()
    _probe.destroy()
    HAS_DISPLAY = True
except tk.TclError:
    HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(
    not HAS_DISPLAY, reason="no display available (try: xvfb-run -a python3 -m pytest tests/test_gui.py)"
)

import gui  # noqa: E402  (import after the skip check, and after sys.path fix)
from input_backend import MockBackend  # noqa: E402


def test_bad_uri_is_rejected_without_starting_a_connection():
    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        app.uri_var.set("not-a-valid-uri")
        app.connect()
        root.update()
        assert "ws://" in app.status_var.get()
        assert app.connected is False
    finally:
        app._on_close()


def test_failed_backend_resets_the_button():
    # Regression test: an earlier version of gui.py called root.after()
    # directly from the background thread to report backend failures,
    # which raises RuntimeError outside of mainloop(). This exercises
    # that exact failure path via the queue-based fix instead.
    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        app.uri_var.set("ws://127.0.0.1:1/nonexistent-port-for-testing")
        app.connect()
        for _ in range(15):
            time.sleep(0.1)
            root.update()
            if app.connect_button.cget("text") == "Connect":
                break
        assert app.connect_button.cget("text") == "Connect"
        assert app.connected is False
    finally:
        app._on_close()


def test_connect_disconnect_round_trip(monkeypatch):
    # No /dev/uinput in most test environments, so swap in MockBackend —
    # this test is about the threading/queue/asyncio wiring, not uinput
    # itself (that's smoke_test.py's job, on real hardware).
    monkeypatch.setattr(gui, "UinputBackend", MockBackend)

    import websockets

    async def fake_phone_server(websocket):
        await websocket.wait_closed()

    async def serve_forever():
        async with websockets.serve(fake_phone_server, "127.0.0.1", 8767):
            await asyncio.Event().wait()

    threading.Thread(target=lambda: asyncio.run(serve_forever()), daemon=True).start()
    time.sleep(0.3)

    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        app.uri_var.set("ws://127.0.0.1:8767")
        app.connect()

        connected_ok = False
        for _ in range(20):
            time.sleep(0.1)
            root.update()
            if "Connected to" in app.status_var.get():
                connected_ok = True
                break
        assert connected_ok, f"never saw Connected status, last was: {app.status_var.get()}"
        assert app.connect_button.cget("text") == "Disconnect"

        app.disconnect()
        for _ in range(20):
            time.sleep(0.1)
            root.update()
            if app.connect_button.cget("text") == "Connect":
                break
        assert app.connect_button.cget("text") == "Connect"
    finally:
        app._on_close()


def test_bare_ws_scheme_with_no_host_is_rejected():
    # Regression test: the address field defaults to bare "ws://" (no
    # host). That passed the old "starts with ws://" check trivially
    # and crashed a background thread with InvalidURI under real
    # testing on an actual machine.
    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        app.uri_var.set("ws://")
        app.connect()
        root.update()
        assert "address" in app.status_var.get().lower()
        assert app.connected is False
    finally:
        app._on_close()


def test_unexpected_exception_type_still_updates_status(monkeypatch):
    # Regression test: a real run produced websockets.exceptions.
    # ConnectionClosedError (phone dropped the connection mid-session,
    # e.g. backgrounded). That's neither CancelledError nor OSError, so
    # it fell through both specific except clauses uncaught. The button
    # still reset correctly (finally always runs) but the status text
    # was never told the connection had died, and stayed on stale
    # "Connected to ..." text. This simulates any such "some other
    # exception type" failure without needing to reproduce the exact
    # real-world trigger, since the fix is about the except clause
    # catching it at all, not about websockets internals specifically.
    monkeypatch.setattr(gui, "UinputBackend", MockBackend)

    class SomeOtherFailure(Exception):
        pass

    async def fake_run_client(uri, backend, on_status=None):
        if on_status:
            on_status(f"Connected to {uri}")
        raise SomeOtherFailure("simulated non-OSError, non-CancelledError failure")

    monkeypatch.setattr(gui, "run_client", fake_run_client)

    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        app.uri_var.set("ws://127.0.0.1:9")
        app.connect()

        saw_lost = False
        for _ in range(20):
            time.sleep(0.1)
            root.update()
            if "Connection lost" in app.status_var.get():
                saw_lost = True
                break

        assert saw_lost, f"status never updated after the failure, stayed at: {app.status_var.get()}"
        assert app.connect_button.cget("text") == "Connect"
        assert app.connected is False
    finally:
        app._on_close()


def test_rendezvous_announce_autofills_and_connects(monkeypatch):
    # Simulates a phone that scanned the QR code: connects to the
    # rendezvous port and sends its ws:// address. The app should pick
    # this up, fill the address field, and connect automatically —
    # without the connect() call itself needing real uinput.
    monkeypatch.setattr(gui, "UinputBackend", MockBackend)
    monkeypatch.setattr(gui, "RENDEZVOUS_PORT", 8768)

    import websockets

    async def fake_phone_server(websocket):
        await websocket.wait_closed()

    async def serve_forever():
        async with websockets.serve(fake_phone_server, "127.0.0.1", 8769):
            await asyncio.Event().wait()

    threading.Thread(target=lambda: asyncio.run(serve_forever()), daemon=True).start()
    time.sleep(0.3)

    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()

        # Give the rendezvous listener thread a moment to actually bind
        # before a fake "phone" tries to connect to it.
        time.sleep(0.3)

        with socket.create_connection(("127.0.0.1", 8768), timeout=2) as conn:
            conn.sendall(b"ws://127.0.0.1:8769\n")

        autofilled = False
        for _ in range(50):
            time.sleep(0.1)
            root.update()
            if app.uri_var.get() == "ws://127.0.0.1:8769":
                autofilled = True
                break
        assert autofilled, f"address field never got the announced URI, was: {app.uri_var.get()}"

        connected_ok = False
        for _ in range(50):
            time.sleep(0.1)
            root.update()
            if "Connected to" in app.status_var.get():
                connected_ok = True
                break
        assert connected_ok, f"never auto-connected, last status: {app.status_var.get()}"
    finally:
        app._on_close()

