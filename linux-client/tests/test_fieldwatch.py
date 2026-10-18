"""Mirroring the desktop's focused text field to the phone."""

import asyncio
import json
import os
import socket
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import client  # noqa: E402
import fieldwatch  # noqa: E402
from fieldwatch import FieldSnapshot, FieldWatcher, LatestBox, snapshot_message, window_text  # noqa: E402
from input_backend import MockBackend  # noqa: E402
from protocol import ProtocolError, make_field_message  # noqa: E402

websockets = pytest.importorskip("websockets")


class FakeBackend:
    """Stands in for AT-SPI: tests push snapshots as if the focused field changed."""

    def __init__(self):
        self.emit = None

    def start(self, on_snapshot):
        self.emit = on_snapshot


# ------------------------------------------------------------- windowing

def test_short_text_is_shown_whole_with_the_caret_where_it_is():
    assert window_text("hello", 5) == ("hello", 5)
    assert window_text("hello", 2) == ("hello", 2)
    assert window_text("", 0) == ("", 0)


def test_only_the_carets_own_line_is_shown():
    text = "first line\nsecond line\nthird"
    shown, caret = window_text(text, text.index("second") + 3)
    assert shown == "second line" and caret == 3


def test_a_long_line_is_cut_around_the_caret_with_ellipses_and_the_caret_follows():
    text = "a" * 300 + "X" + "b" * 300
    shown, caret = window_text(text, 300)
    assert shown.startswith("\u2026") and shown.endswith("\u2026")
    assert shown[caret] == "X"  # the caret still points at the same character
    assert len(shown) < 200


def test_caret_is_clamped_into_the_text():
    assert window_text("abc", 99) == ("abc", 3)
    assert window_text("abc", -5) == ("abc", 0)


def test_caret_at_the_end_of_a_line_before_a_newline():
    assert window_text("ab\ncd", 2) == ("ab", 2)
    assert window_text("ab\ncd", 3) == ("cd", 0)


# ------------------------------------------------------------- messages

def test_no_focused_field_is_a_minimal_message():
    assert snapshot_message(FieldSnapshot(False)) == {"t": "field", "focused": False}


def test_a_focused_field_carries_text_caret_and_name():
    msg = snapshot_message(FieldSnapshot(True, "cats", 2, False, "Search"))
    assert msg == {"t": "field", "focused": True, "text": "cats", "caret": 2, "password": False, "name": "Search"}


def test_password_text_never_leaves_even_if_a_backend_passes_it_through():
    msg = snapshot_message(FieldSnapshot(True, "hunter2", 7, True, "Password"))
    assert "hunter2" not in json.dumps(msg)
    assert msg["text"] == "\u2022" * 7 and msg["password"] is True and msg["caret"] == 7


def test_a_very_long_password_is_capped():
    msg = snapshot_message(FieldSnapshot(True, "x" * 500, 500, True))
    assert len(msg["text"]) == fieldwatch.MAX_PASSWORD_BULLETS


def test_field_message_validation():
    with pytest.raises(ProtocolError):
        make_field_message("yes")
    with pytest.raises(ProtocolError):
        make_field_message(True, 5)
    with pytest.raises(ProtocolError):
        make_field_message(True, "a", -1)
    assert make_field_message(True, "ab", 99)["caret"] == 2  # clamped, not rejected


# ------------------------------------------------------------- watcher

def test_a_new_listener_immediately_gets_the_current_state():
    backend = FakeBackend()
    watcher = FieldWatcher(backend)
    watcher.start()
    got = []
    watcher.set_sink(got.append)
    assert got == [{"t": "field", "focused": False}]

    backend.emit(FieldSnapshot(True, "abc", 3, False, "Search"))
    got2 = []
    watcher.set_sink(got2.append)  # a reconnect
    assert got2[0]["text"] == "abc"


def test_repeated_identical_states_are_sent_once():
    backend = FakeBackend()
    watcher = FieldWatcher(backend)
    watcher.start()
    got = []
    watcher.set_sink(got.append)
    for _ in range(5):
        backend.emit(FieldSnapshot(True, "abc", 3))
    assert [m["text"] for m in got if m["focused"]] == ["abc"]
    backend.emit(FieldSnapshot(True, "abcd", 4))
    assert got[-1]["text"] == "abcd"


def test_caret_moves_alone_are_reported():
    backend = FakeBackend()
    watcher = FieldWatcher(backend)
    watcher.start()
    got = []
    watcher.set_sink(got.append)
    backend.emit(FieldSnapshot(True, "abc", 3))
    backend.emit(FieldSnapshot(True, "abc", 1))
    assert [m["caret"] for m in got if m["focused"]] == [3, 1]


def test_losing_focus_is_reported():
    backend = FakeBackend()
    watcher = FieldWatcher(backend)
    watcher.start()
    got = []
    watcher.set_sink(got.append)
    backend.emit(FieldSnapshot(True, "abc", 3))
    backend.emit(FieldSnapshot(False))
    assert got[-1] == {"t": "field", "focused": False}


def test_events_with_no_listener_are_remembered_not_lost_or_crashing():
    backend = FakeBackend()
    watcher = FieldWatcher(backend)
    watcher.start()
    backend.emit(FieldSnapshot(True, "typed before anyone connected", 5))
    got = []
    watcher.set_sink(got.append)
    assert got[0]["text"] == "typed before anyone connected"


# ------------------------------------------------------------- LatestBox

def test_latest_box_keeps_only_the_newest_message_when_the_reader_is_slow():
    async def scenario():
        box = LatestBox(asyncio.get_running_loop())
        t = threading.Thread(target=lambda: [box.put({"n": i}) for i in range(50)])
        t.start()
        t.join()
        await asyncio.sleep(0.05)
        return await asyncio.wait_for(box.get(), 1)

    assert asyncio.run(scenario()) == {"n": 49}


def test_latest_box_put_after_the_loop_closed_does_not_raise():
    loop = asyncio.new_event_loop()
    box = LatestBox(loop)
    loop.close()
    box.put({"n": 1})  # must be silent: the session ended while a callback was in flight


# ------------------------------------------------------------- end to end

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_the_phone_receives_the_current_state_then_every_change(monkeypatch):
    backend = FakeBackend()
    watcher = FieldWatcher(backend)
    watcher.start()
    monkeypatch.setattr(fieldwatch, "get_watcher", lambda: watcher)
    port = _free_port()
    received = []

    async def phone(ws):
        async def push_changes():
            await asyncio.sleep(0.2)
            backend.emit(FieldSnapshot(True, "search te", 9, False, "Search"))
            await asyncio.sleep(0.1)
            backend.emit(FieldSnapshot(True, "search tex", 10, False, "Search"))
            await asyncio.sleep(0.1)
            backend.emit(FieldSnapshot(True, "pass", 4, True, "Password"))
            await asyncio.sleep(0.3)
            await ws.close()

        pusher = asyncio.ensure_future(push_changes())
        async for raw in ws:
            received.append(json.loads(raw))
        await pusher

    async def scenario():
        async with websockets.serve(phone, "127.0.0.1", port):
            await asyncio.wait_for(client.run_client(f"ws://127.0.0.1:{port}", MockBackend()), timeout=8)

    asyncio.run(scenario())
    assert received[0] == {"t": "field", "focused": False}            # told the state on connect
    assert [m["text"] for m in received if m.get("focused")][:2] == ["search te", "search tex"]
    last = received[-1]
    assert last["password"] is True and "pass" not in last["text"]    # masked on the wire
    assert watcher._sink is None                                       # sink removed when the session ended


def test_a_session_without_field_support_still_works(monkeypatch):
    monkeypatch.setattr(fieldwatch, "get_watcher", lambda: None)
    port = _free_port()
    received = []

    async def phone(ws):
        await ws.send(json.dumps({"t": "move", "dx": 5, "dy": 3}))
        await asyncio.sleep(0.2)
        await ws.close()
        received.append("closed")

    async def scenario():
        backend = MockBackend()
        async with websockets.serve(phone, "127.0.0.1", port):
            await asyncio.wait_for(client.run_client(f"ws://127.0.0.1:{port}", backend), timeout=8)
        return backend

    backend = asyncio.run(scenario())
    assert received == ["closed"]


def test_get_watcher_is_off_when_disabled_by_the_environment(monkeypatch):
    monkeypatch.setattr(fieldwatch, "_watcher_tried", False)
    monkeypatch.setattr(fieldwatch, "_watcher", None)
    monkeypatch.setenv("REMOTE_HID_NO_FIELD", "1")
    assert fieldwatch.get_watcher() is None
