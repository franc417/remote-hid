"""Desktop-side client: connects to the phone's WebSocket server and
feeds every message it receives into an InputBackend.
"""

import asyncio
import json
import sys

import websockets

from handler import handle_message


async def run_client(uri: str, backend, on_status=None) -> None:
    # ping_interval stays short (20s) so pings keep flowing regularly —
    # good for NAT/firewall keepalive and for genuinely detecting a
    # dead connection reasonably fast. ping_timeout is set much longer
    # (10 min): this is how long the app tolerates sitting idle (phone
    # set down, no touches) without deciding the connection is dead.
    # Needs to stay under the Android side's own socket read timeout
    # (RemoteHidService.kt) or that becomes the real limiting factor
    # regardless of this value — learned that the hard way already.
    async with websockets.connect(uri, ping_interval=20, ping_timeout=600) as ws:
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
