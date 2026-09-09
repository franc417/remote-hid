"""Desktop-side client: connects to the phone's WebSocket server and
feeds every message it receives into an InputBackend.
"""

import asyncio
import json
import sys

import websockets

from handler import handle_message


async def run_client(uri: str, backend) -> None:
    async with websockets.connect(uri) as ws:
        print(f"[client] connected to {uri}")
        async for raw_frame in ws:
            try:
                msg = json.loads(raw_frame)
            except json.JSONDecodeError:
                print(f"[client] dropping non-JSON frame: {raw_frame!r}")
                continue
            handle_message(msg, backend)
        print("[client] connection closed")


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
