"""Tests for the Tkinter GUI wrapper (gui.py). These need a real or
virtual display — skipped automatically if tkinter can't open a window,
so this doesn't break on headless machines without Xvfb. On your actual
desktop (Mint or otherwise), these run for real against a real display.

Run with: python3 -m pytest tests/test_gui.py -v
Headless: xvfb-run -a python3 -m pytest tests/test_gui.py -v
"""

import asyncio
import os
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
        root.destroy()


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
        root.destroy()


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
        root.destroy()
