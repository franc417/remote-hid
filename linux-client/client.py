"""Desktop-side client: connects to the phone's WebSocket server and
feeds every message it receives into an InputBackend.
"""

import asyncio
import json
import sys

import websockets

from handler import handle_message


async def run_client(uri: str, backend, on_status=None) -> None:
    # Explicit rather than relying on the library's defaults (which
    # happen to also be 20/20 today, but defaults can change): this
    # value has to stay well under the Android side's socket read
    # timeout (60s, in RemoteHidService.kt) for the built-in keepalive
    # to actually do its job. A real bug taught us this the hard way —
    # Android's timeout used to be a default 5s, shorter than even the
    # library's own 20s ping interval, so the two were never compatible
    # regardless of what either side's actual value was.
    async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
        print(f"[client] connected to {uri}")
        if on_status:
            on_status(f"Connected to {uri}")
        async for raw_frame in ws:
            try:
                msg = json.loads(raw_frame)
            except json.JSONDecodeError:
                print(f"[client] dropping non-JSON frame: {raw_frame!r}")
                continue
            handle_message(msg, backend)
        print("[client] connection closed")
        if on_status:
            on_status("Disconnected (connection closed)")


def main():
    if len(sys.argv) != 2:
        print("usage: python3 client.py ws://<phone-ip>:<port>")
        sys.exit(1)

    uri = sys.argv[1]

    try:
        from input_backend import UinputBackend
        backend = UinputBackend()
    except Exception as exc:
        # Missing evdev, no /dev/uinput, no permission, wrong platform, etc.
        print(f"[client] could not start the input backend: {exc}")
        print("[client] see README.md for uinput permission setup")
        sys.exit(1)

    try:
        asyncio.run(run_client(uri, backend))
    except KeyboardInterrupt:
        pass
    finally:
        backend.close()


if __name__ == "__main__":
    main()
