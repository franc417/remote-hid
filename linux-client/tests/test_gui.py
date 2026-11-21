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
        # This test pins the original contract: a drop ends the session. That is
        # what the app does with auto-reconnect off; with it on (the default) the
        # app keeps retrying instead -- covered by the reconnect tests below.
        app.auto_var.set(False)
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



# ---------------------------------------------------------------- auto-reconnect

import reconnect  # noqa: E402


def _wait(root, cond, seconds=5.0):
    """Pump Tk (the GUI only applies status changes from its own poll loop)
    until cond() holds. Returns whether it did, rather than raising, so the
    caller's assert can say what the state actually was."""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def _reconnect_app(monkeypatch, tmp_path, fake_run_client):
    monkeypatch.setattr(gui, "UinputBackend", MockBackend)
    monkeypatch.setattr(gui, "run_client", fake_run_client)
    monkeypatch.setattr(gui, "CONFIG_PATH", tmp_path / "last_connection.json")  # known_path() follows it
    monkeypatch.setattr(gui, "backoff_delay", lambda n: 0.02)  # don't make the suite sit through real waits
    monkeypatch.setattr(gui, "local_ip", lambda: "10.0.0.5")
    monkeypatch.setattr(gui, "scan_subnet", lambda ip: [])  # no real network scanning in tests
    monkeypatch.setattr(gui, "scan_anchor_ips", lambda: ["10.0.0.5"])  # one fake local subnet to scan
    monkeypatch.setattr(gui, "tether_uris", lambda: [])  # no real `ip` calls either
    monkeypatch.setattr(gui, "prioritize", lambda targets: list(targets))  # no real probes either
    root = tk.Tk()
    return root, gui.App(root)


def test_drop_after_connecting_retries_and_keeps_the_reason_visible(monkeypatch, tmp_path):
    calls = []

    async def fake_run_client(uri, backend, on_status=None):
        calls.append(uri)
        on_status(f"Connected to {uri}")
        if len(calls) == 1:
            raise RuntimeError("phone went away")
        await asyncio.sleep(30)  # second time it stays up until cancelled

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: len(calls) >= 2), f"never retried, calls={calls}"
        assert calls == ["ws://10.0.0.7:8765"] * 2
        assert _wait(root, lambda: app.status_var.get().startswith("Connected"))
        assert app.connect_button.cget("text") == "Disconnect"  # still "in session", just retried

        app.disconnect()
        # disconnect() flips the button on the UI thread at once; the worker
        # thread posts "Disconnected" a moment later, so wait for that.
        assert _wait(root, lambda: app.status_var.get() == "Disconnected")
        assert app.connect_button.cget("text") == "Connect"
        assert app.connected is False
    finally:
        app._on_close()


def test_retry_status_says_why_not_just_that_it_is_retrying(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        on_status(f"Connected to {uri}")
        raise RuntimeError("phone went away")

    monkeypatch.setattr(gui, "backoff_delay", lambda n: 5)  # park it in the wait so the text stays put
    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    monkeypatch.setattr(gui, "backoff_delay", lambda n: 5)
    try:
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: "Retrying" in app.status_var.get())
        text = app.status_var.get()
        assert "Connection lost" in text and "phone went away" in text, text
    finally:
        app._on_close()


def test_a_first_attempt_that_never_connects_does_not_retry(monkeypatch, tmp_path):
    attempts = []

    async def fake_run_client(uri, backend, on_status=None):
        attempts.append(uri)
        raise OSError("connection refused")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        app.uri_var.set("ws://10.0.0.99:8765")  # a typo'd / wrong address
        app.connect()
        assert _wait(root, lambda: app.connect_button.cget("text") == "Connect")
        time.sleep(0.2)
        root.update()
        assert attempts == ["ws://10.0.0.99:8765"]  # tried once, stopped -- not retried forever
        assert "Could not connect" in app.status_var.get()
        assert reconnect.load_known(gui.known_path(), gui.CONFIG_PATH) == []  # a failure is never remembered
    finally:
        app._on_close()


def test_autostart_keeps_trying_until_the_remembered_phone_appears(monkeypatch, tmp_path):
    attempts = []

    async def fake_run_client(uri, backend, on_status=None):
        attempts.append(uri)
        if len(attempts) < 3:
            raise OSError("not up yet")
        on_status(f"Connected to {uri}")
        await asyncio.sleep(30)

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        reconnect.remember("ws://10.0.0.7:8765", gui.known_path(), gui.CONFIG_PATH)
        app.autostart()
        assert app.uri_var.get() == "ws://10.0.0.7:8765"
        assert _wait(root, lambda: app.status_var.get().startswith("Connected")), app.status_var.get()
        assert attempts[:3] == ["ws://10.0.0.7:8765"] * 3
    finally:
        app._on_close()


def test_autostart_with_nothing_remembered_does_nothing(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        raise AssertionError("must not connect with no remembered phone")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        app.autostart()
        root.update()
        assert app.connected is False
    finally:
        app._on_close()


def test_autostart_respects_the_toggle(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        raise AssertionError("auto-reconnect is off; must not connect")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        reconnect.remember("ws://10.0.0.7:8765", gui.known_path(), gui.CONFIG_PATH)
        app.auto_var.set(False)
        root.update()
        app.autostart()
        assert app.connected is False
    finally:
        app._on_close()


def test_a_phone_whose_address_changed_is_found_by_the_subnet_scan(monkeypatch, tmp_path):
    attempts = []

    async def fake_run_client(uri, backend, on_status=None):
        attempts.append(uri)
        if uri != "ws://10.0.0.42:8765":  # the phone's new lease; the old one is dead
            raise OSError("no route")
        on_status(f"Connected to {uri}")
        await asyncio.sleep(30)

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    monkeypatch.setattr(gui, "scan_subnet", lambda ip: ["ws://10.0.0.42:8765"])
    try:
        reconnect.remember("ws://10.0.0.7:8765", gui.known_path(), gui.CONFIG_PATH)
        app.autostart()
        assert _wait(root, lambda: app.status_var.get().startswith("Connected")), app.status_var.get()
        assert attempts[-1] == "ws://10.0.0.42:8765"
        # ...and it's now what's remembered first, so next launch goes straight there
        assert reconnect.load_known(gui.known_path(), gui.CONFIG_PATH)[0] == "ws://10.0.0.42:8765"
    finally:
        app._on_close()


def test_disconnect_during_the_retry_wait_stops_immediately(monkeypatch, tmp_path):
    attempts = []

    async def fake_run_client(uri, backend, on_status=None):
        attempts.append(uri)
        on_status(f"Connected to {uri}")
        raise RuntimeError("dropped")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    monkeypatch.setattr(gui, "backoff_delay", lambda n: 30)  # a long wait we must be able to interrupt
    try:
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: "Retrying in 30s" in app.status_var.get())
        t0 = time.time()
        app.disconnect()
        # "Disconnected" is only posted once the worker's loop has actually
        # exited, so seeing it within 2s proves the 30s wait was interrupted
        # (the button alone isn't proof: disconnect() resets it immediately).
        assert _wait(root, lambda: app.status_var.get() == "Disconnected", seconds=3)
        assert time.time() - t0 < 2, "disconnect had to wait out the retry delay"
        assert len(attempts) == 1  # no retry sneaked in after the click
    finally:
        app._on_close()


# ------------------------------------------------ switching and stale sessions

def _announce(port, uri):
    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        conn.sendall(uri.encode() + b"\n")


def test_scanning_a_second_phone_switches_to_it_and_drops_the_first(monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "UinputBackend", MockBackend)
    monkeypatch.setattr(gui, "RENDEZVOUS_PORT", 8780)
    monkeypatch.setattr(gui, "CONFIG_PATH", tmp_path / "last_connection.json")
    import websockets

    opened, closed = [], []

    def make_phone(name, port):
        async def phone(ws):
            opened.append(name)
            try:
                await ws.wait_closed()
            finally:
                closed.append(name)

        async def serve():
            async with websockets.serve(phone, "127.0.0.1", port):
                await asyncio.Event().wait()

        threading.Thread(target=lambda: asyncio.run(serve()), daemon=True).start()

    make_phone("A", 8781)
    make_phone("B", 8782)
    time.sleep(0.3)

    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        time.sleep(0.3)
        app.uri_var.set("ws://127.0.0.1:8781")
        app.connect()
        assert _wait(root, lambda: app.session.target == "ws://127.0.0.1:8781")
        first = app.session

        _announce(8780, "ws://127.0.0.1:8782")  # scan phone B while connected to A
        assert _wait(root, lambda: app.session is not first and app.session.target == "ws://127.0.0.1:8782")
        assert _wait(root, lambda: "A" in closed), "the first phone was never released"
        assert _wait(root, lambda: "Connected to ws://127.0.0.1:8782" in app.status_var.get()), app.status_var.get()
        assert app.connect_button.cget("text") == "Disconnect"
        # The first session winding down must not have reset the live one's button.
        root.update(); time.sleep(0.3); root.update()
        assert app.connect_button.cget("text") == "Disconnect"
    finally:
        app._on_close()


def test_scanning_the_phone_you_are_already_connected_to_does_nothing(monkeypatch, tmp_path):
    runs = []

    async def fake_run_client(uri, backend, on_status=None):
        runs.append(uri)
        on_status(f"Connected to {uri}")
        await asyncio.Event().wait()

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "RENDEZVOUS_PORT", 8783)
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: app.session.target == "ws://10.0.0.7:8765")
        app.status_queue.put(("announced_uri", "ws://10.0.0.7:8765", None))
        _wait(root, lambda: False, 0.5)
        assert runs == ["ws://10.0.0.7:8765"]
    finally:
        app._on_close()


def test_a_takeover_stops_retrying_and_says_why(monkeypatch, tmp_path):
    from protocol import SessionReplaced
    runs = []

    async def fake_run_client(uri, backend, on_status=None):
        runs.append(uri)
        on_status(f"Connected to {uri}")
        raise SessionReplaced("x")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: app.connect_button.cget("text") == "Connect" and "took over" in app.status_var.get())
        _wait(root, lambda: False, 0.4)
        assert runs == ["ws://10.0.0.7:8765"], "must not reconnect after being taken over"
        assert "took over" in app.status_var.get()
    finally:
        app._on_close()


def test_messages_from_a_replaced_session_are_ignored(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        on_status(f"Connected to {uri}")
        await asyncio.Event().wait()

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: app.session.target is not None)
        stale = gui.Session()
        app.status_queue.put(("reset_button", None, stale))
        app.status_queue.put(("status", "Disconnected", stale))
        _wait(root, lambda: False, 0.4)
        assert app.connect_button.cget("text") == "Disconnect"
        assert "Connected to" in app.status_var.get()
    finally:
        app._on_close()


def test_disconnect_after_the_session_loop_already_ended_does_not_crash(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        raise OSError("refused")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: app.connect_button.cget("text") == "Connect")
        app.session.loop.close() if not app.session.loop.is_closed() else None
        app.disconnect()  # its loop is gone: must be a no-op, not a RuntimeError
    finally:
        app._on_close()


# ------------------------------------------------ USB cable awareness

def test_a_plugged_in_phone_is_tried_right_after_the_typed_address_and_before_remembered_ones(monkeypatch, tmp_path):
    tried = []

    async def fake_run_client(uri, backend, on_status=None):
        tried.append(uri)
        raise OSError("refused")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "tether_uris", lambda: ["ws://192.168.42.129:8765"])
        reconnect.remember("ws://10.0.0.7:8765", gui.known_path(), gui.CONFIG_PATH)
        app.uri_var.set("ws://10.0.0.9:8765")
        app.connect()
        assert _wait(root, lambda: len(tried) >= 3)
        assert tried[:3] == ["ws://10.0.0.9:8765", "ws://192.168.42.129:8765", "ws://10.0.0.7:8765"]
    finally:
        app._on_close()


def test_the_cable_address_is_re_read_every_round_so_a_changed_tether_subnet_is_followed(monkeypatch, tmp_path):
    tried = []

    async def fake_run_client(uri, backend, on_status=None):
        tried.append(uri)
        if uri == "ws://192.168.77.1:8765":
            on_status(f"Connected to {uri}")
            await asyncio.Event().wait()
        raise OSError("refused")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        rounds = iter([["ws://192.168.42.129:8765"], ["ws://192.168.77.1:8765"]])
        last = {"v": ["ws://192.168.42.129:8765"]}

        def tether():
            last["v"] = next(rounds, last["v"])
            return last["v"]

        monkeypatch.setattr(gui, "tether_uris", tether)
        app.uri_var.set("ws://10.0.0.9:8765")
        app.connect(persistent=True)
        assert _wait(root, lambda: app.status_var.get().startswith("Connected to ws://192.168.77.1"), 8), tried
    finally:
        app._on_close()


def test_an_empty_address_box_fills_itself_from_a_plugged_in_phone(monkeypatch, tmp_path):
    seen = []

    async def fake_run_client(uri, backend, on_status=None):
        seen.append(uri)
        on_status(f"Connected to {uri}")
        await asyncio.Event().wait()

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "tether_uris", lambda: ["ws://192.168.42.129:8765"])
        app.uri_var.set("")
        app.connect()
        assert _wait(root, lambda: seen == ["ws://192.168.42.129:8765"])
        assert app.uri_var.get() == "ws://192.168.42.129:8765"
    finally:
        app._on_close()


def test_an_empty_address_box_with_no_cable_asks_for_an_address(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        raise AssertionError("must not connect")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        app.uri_var.set("")
        app.connect()
        assert "Enter a full address" in app.status_var.get()
        assert not app.connected
    finally:
        app._on_close()


# ------------------------------------------------ pairing without a camera

def test_the_pairing_qr_is_large_crisp_and_has_the_full_quiet_zone():
    import qrcode as qrlib
    payload = "192.168.100.5:8780"
    img = gui.make_qr_image(payload, 300)
    assert 240 <= img.width <= 300 and img.width == img.height   # was 180px
    qr = qrlib.QRCode(error_correction=qrlib.constants.ERROR_CORRECT_M, box_size=1, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    modules = qr.modules_count + 8
    scale = img.width // modules
    assert scale >= 6, f"only {scale}px per module: too small for a phone camera"
    assert img.width == scale * modules                          # whole pixels per module: no resampling blur
    px = img.load()
    # the 4-module quiet zone is white all around, and the first module of the finder pattern is black
    assert all(px[x, y] == (255, 255, 255) for x in range(0, 4 * scale) for y in (0, img.height // 2, img.height - 1))
    assert px[4 * scale + scale // 2, 4 * scale + scale // 2] == (0, 0, 0)


def test_an_unreadable_size_still_produces_a_valid_image():
    assert gui.make_qr_image("1.2.3.4:5", 100).width >= 25


def test_find_phone_connects_to_the_only_phone_it_finds(monkeypatch, tmp_path):
    seen = []

    async def fake_run_client(uri, backend, on_status=None):
        seen.append(uri)
        on_status(f"Connected to {uri}")
        await asyncio.Event().wait()

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "scan_subnet", lambda ip: ["ws://10.0.0.77:8765"])
        monkeypatch.setattr(gui, "filter_reachable", lambda uris: list(uris))
        app.uri_var.set("ws://")
        app.find_phone()
        assert app.find_button.cget("state") == "disabled"        # no double clicks while searching
        assert _wait(root, lambda: seen == ["ws://10.0.0.77:8765"])
        assert app.find_button.cget("state") == "normal"
        assert app.uri_var.get() == "ws://10.0.0.77:8765"
    finally:
        app._on_close()


def test_find_phone_prefers_the_cable_and_says_when_there_are_several(monkeypatch, tmp_path):
    seen = []

    async def fake_run_client(uri, backend, on_status=None):
        seen.append(uri)
        on_status(f"Connected to {uri}")
        await asyncio.Event().wait()

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "tether_uris", lambda: ["ws://192.168.42.129:8765"])
        monkeypatch.setattr(gui, "filter_reachable", lambda uris: list(uris))
        monkeypatch.setattr(gui, "scan_subnet", lambda ip: ["ws://10.0.0.77:8765", "ws://192.168.42.129:8765"])
        app.find_phone()
        assert _wait(root, lambda: seen == ["ws://192.168.42.129:8765"])   # cable first, duplicates merged
    finally:
        app._on_close()


def test_a_cable_gateway_that_does_not_answer_is_not_offered(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        raise AssertionError("nothing answered, so nothing should connect")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "tether_uris", lambda: ["ws://192.168.42.129:8765"])
        monkeypatch.setattr(gui, "filter_reachable", lambda uris: [])   # a router, or the app is closed
        app.find_phone()
        assert _wait(root, lambda: app.status_var.get().startswith("No phone found"))
        assert app.find_button.cget("state") == "normal"
    finally:
        app._on_close()


def test_find_phone_with_nothing_around_explains_what_to_do(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        raise AssertionError("must not connect")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "filter_reachable", lambda uris: [])
        app.find_phone()
        assert _wait(root, lambda: "No phone found" in app.status_var.get())
        assert "Wi-Fi" in app.status_var.get() and "USB tethering" in app.status_var.get()
    finally:
        app._on_close()


def test_a_search_that_crashes_does_not_leave_the_button_dead(monkeypatch, tmp_path):
    async def fake_run_client(uri, backend, on_status=None):
        raise AssertionError("must not connect")

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        def boom(ip):
            raise RuntimeError("scan blew up")
        monkeypatch.setattr(gui, "scan_subnet", boom)
        monkeypatch.setattr(gui, "filter_reachable", lambda uris: [])
        app.find_phone()
        assert _wait(root, lambda: app.find_button.cget("state") == "normal")
    finally:
        app._on_close()


def test_finding_the_phone_you_are_already_connected_to_does_not_reconnect(monkeypatch, tmp_path):
    runs = []

    async def fake_run_client(uri, backend, on_status=None):
        runs.append(uri)
        on_status(f"Connected to {uri}")
        await asyncio.Event().wait()

    root, app = _reconnect_app(monkeypatch, tmp_path, fake_run_client)
    try:
        monkeypatch.setattr(gui, "filter_reachable", lambda uris: list(uris))
        monkeypatch.setattr(gui, "scan_subnet", lambda ip: ["ws://10.0.0.7:8765"])
        app.uri_var.set("ws://10.0.0.7:8765")
        app.connect()
        assert _wait(root, lambda: app.session.target == "ws://10.0.0.7:8765")
        app.find_phone()
        assert _wait(root, lambda: app.status_var.get().startswith("Already connected"))
        assert runs == ["ws://10.0.0.7:8765"]
    finally:
        app._on_close()


# ---------------------------------------------------------------- the QR code follows the network

import netinfo  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _qr_app(monkeypatch, tmp_path, ips_now, port=None):
    """An App whose QR code looks at `ips_now()` (a list it can change) every 50 ms, with no real `ip` calls, and its own
    pairing port (an App left over from an earlier test still holds the default one)."""
    monkeypatch.setattr(gui, "RENDEZVOUS_PORT", port or _free_port())
    monkeypatch.setattr(gui, "UinputBackend", MockBackend)
    monkeypatch.setattr(gui, "CONFIG_PATH", tmp_path / "last_connection.json")
    monkeypatch.setattr(gui, "ADDRESS_POLL_SECONDS", 0.05)
    monkeypatch.setattr(gui, "reachable_ips", lambda limit=4: list(ips_now()))
    monkeypatch.setattr(netinfo, "reachable_ips", lambda limit=4: list(ips_now()))
    monkeypatch.setattr(netinfo, "describe_ips", lambda ips: [f"{i}  (Wi-Fi)" for i in ips])
    root = tk.Tk()
    return root, gui.App(root)


def test_the_qr_code_moves_to_the_new_address_when_the_network_changes(monkeypatch, tmp_path):
    ips = ["192.168.0.105"]
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ips)
    try:
        assert _wait(root, lambda: "192.168.0.105  (Wi-Fi)" in app.addr_var.get())
        first = app._qr_photo
        ips[:] = ["10.20.30.7"]                                         # the laptop joined another network
        assert _wait(root, lambda: "10.20.30.7  (Wi-Fi)" in app.addr_var.get()), app.addr_var.get()
        assert "192.168.0.105" not in app.addr_var.get()
        assert app._qr_photo is not first                               # the picture was redrawn for the new address
        assert str(gui.RENDEZVOUS_PORT) in app.addr_var.get()
    finally:
        app._on_close()


def test_the_qr_code_is_not_redrawn_when_nothing_changed(monkeypatch, tmp_path):
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ["192.168.0.105"])
    try:
        assert _wait(root, lambda: "(Wi-Fi)" in app.addr_var.get())
        photo = app._qr_photo
        end = time.time() + 0.4
        while time.time() < end:
            root.update()
            time.sleep(0.02)
        assert app._qr_photo is photo
    finally:
        app._on_close()


def test_with_no_network_the_qr_goes_away_and_comes_back_by_itself(monkeypatch, tmp_path):
    ips = []
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ips)
    try:
        assert _wait(root, lambda: app.status_var.get().startswith("No network address"))
        assert app._qr_photo is None and "No network address" in app.addr_var.get()
        ips[:] = ["192.168.43.17"]                                      # the phone's hotspot was joined
        assert _wait(root, lambda: "192.168.43.17" in app.addr_var.get())
        assert app._qr_photo is not None
        assert app.status_var.get().startswith("Network found")
        ips[:] = []                                                     # and left again
        assert _wait(root, lambda: app._qr_photo is None)
    finally:
        app._on_close()


def test_two_addresses_are_both_listed_under_the_code(monkeypatch, tmp_path):
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ["192.168.0.105", "192.168.42.17"])
    try:
        assert _wait(root, lambda: "192.168.42.17" in app.addr_var.get())
        assert "192.168.0.105" in app.addr_var.get()
    finally:
        app._on_close()


# ---------------------------------------------------------------- the pairing listener must survive bad connections

def _listening(app, port, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return True
        except OSError:
            time.sleep(0.05)
    return False


def test_a_connection_that_drops_without_saying_anything_does_not_end_the_listener(monkeypatch, tmp_path):
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ["192.168.0.105"], port=8791)
    try:
        assert _listening(app, 8791)
        for _ in range(3):                                              # a port scan, a phone that lost Wi-Fi halfway
            c = socket.create_connection(("127.0.0.1", 8791), timeout=2)
            c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")   # close with a reset
            c.close()
        with socket.create_connection(("127.0.0.1", 8791), timeout=2) as conn:
            conn.sendall(b"ws://127.0.0.1:8792\n")
        assert _wait(root, lambda: app.uri_var.get() == "ws://127.0.0.1:8792")
    finally:
        app._on_close()


def test_a_silent_connection_does_not_hold_up_the_next_phone_for_long(monkeypatch, tmp_path):
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ["192.168.0.105"], port=8793)
    silent = None
    try:
        assert _listening(app, 8793)
        silent = socket.create_connection(("127.0.0.1", 8793), timeout=2)      # connects and says nothing
        time.sleep(0.2)
        with socket.create_connection(("127.0.0.1", 8793), timeout=2) as conn:
            conn.sendall(b"ws://127.0.0.1:8794\n")
        assert _wait(root, lambda: app.uri_var.get() == "ws://127.0.0.1:8794", seconds=8.0)
    finally:
        if silent:
            silent.close()
        app._on_close()


def test_an_announce_that_arrives_in_two_pieces_is_read_whole(monkeypatch, tmp_path):
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ["192.168.0.105"], port=8795)
    try:
        assert _listening(app, 8795)
        with socket.create_connection(("127.0.0.1", 8795), timeout=2) as conn:
            conn.sendall(b"ws://127.0.0.1")
            time.sleep(0.3)
            conn.sendall(b":8796\n")
        assert _wait(root, lambda: app.uri_var.get() == "ws://127.0.0.1:8796")
    finally:
        app._on_close()


def test_something_that_is_not_an_announce_is_ignored(monkeypatch, tmp_path):
    root, app = _qr_app(monkeypatch, tmp_path, lambda: ["192.168.0.105"], port=8797)
    try:
        before = app.uri_var.get()
        assert _listening(app, 8797)
        with socket.create_connection(("127.0.0.1", 8797), timeout=2) as conn:
            conn.sendall(b"GET / HTTP/1.1\r\n\r\n")
        time.sleep(0.4)
        root.update()
        assert app.uri_var.get() == before
    finally:
        app._on_close()


def test_cable_check_button_shows_the_report_and_connects_to_a_phone_it_found(monkeypatch):
    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        calls = []
        monkeypatch.setattr(app, "connect", lambda: calls.append(app.uri_var.get()))
        app.cable_button.config(state=tk.DISABLED)
        report = {"verdict": "phone_found", "uri": "ws://192.168.42.129:8765", "summary": "Phone found on the cable: ws://192.168.42.129:8765", "text": "Cable check\n..."}
        app.status_queue.put(("cable_report", report, None))
        deadline = time.time() + 3
        while time.time() < deadline and not calls:
            root.update()
            time.sleep(0.02)
        assert calls == ["ws://192.168.42.129:8765"]
        assert str(app.cable_button.cget("state")) == "normal" and "Phone found on the cable" in app.status_var.get()
    finally:
        app._on_close()


def test_a_phone_that_answers_on_the_cable_is_connected_to_by_itself(monkeypatch):
    root = tk.Tk()
    try:
        app = gui.App(root)
        root.update()
        calls = []
        monkeypatch.setattr(app, "connect", lambda: calls.append(app.uri_var.get()))
        app.status_queue.put(("cable_phone", "ws://192.168.42.129:8765", None))
        deadline = time.time() + 3
        while time.time() < deadline and not calls:
            root.update()
            time.sleep(0.02)
        assert calls == ["ws://192.168.42.129:8765"] and "connecting" in app.status_var.get()
        app.connected = True                                              # when already connected, a cable phone does not take over
        app.status_queue.put(("cable_phone", "ws://192.168.42.130:8765", None))
        for _ in range(10):
            root.update()
            time.sleep(0.02)
        assert calls == ["ws://192.168.42.129:8765"]
    finally:
        app._on_close()
