"""Exercises the full pipeline over a real WebSocket connection: a fake
in-process "phone" sends protocol messages, the real client.run_client
receives and decodes them, and a MockBackend records what would have
been injected. This proves the network + JSON decode + validation +
dispatch chain works end to end — everything short of touching a real
/dev/uinput device, which this sandbox doesn't have.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import websockets

from client import run_client
from input_backend import MockBackend

TEST_MESSAGES = [
    {"t": "move", "dx": 10, "dy": -4},
    {"t": "click", "button": "left"},
    {"t": "scroll", "dy": 2},
    {"t": "key", "code": "KeyV", "action": "down", "mods": ["ctrl"]},
    {"t": "not-a-real-type"},  # should be dropped, not crash the connection
]


async def _fake_phone_server(websocket):
    for msg in TEST_MESSAGES:
        await websocket.send(json.dumps(msg))
    await websocket.close()


async def _run():
    backend = MockBackend()
    async with websockets.serve(_fake_phone_server, "127.0.0.1", 8765):
        await asyncio.wait_for(run_client("ws://127.0.0.1:8765", backend), timeout=5)
    return backend


def test_full_pipeline_over_real_websocket():
    backend = asyncio.run(_run())
    assert backend.calls == [
        ("move", 10, -4),
        ("click", "left", "click"),
        ("scroll", 2),
        ("key", "KeyV", "down", ("ctrl",)),
    ]
