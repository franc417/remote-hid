"""GUI wrapper for the Linux client. Remembers the last-used phone
address, shows connection status, and runs the WebSocket client in a
background thread so the Tkinter event loop stays responsive.

This is the "app" entry point — run this instead of client.py directly
day to day. client.py's command-line form still works too, for
scripting or debugging.
"""

import asyncio
import json
import queue
import threading
import tkinter as tk
from pathlib import Path

from client import run_client
from input_backend import UinputBackend

CONFIG_PATH = Path.home() / ".config" / "remote-hid" / "last_connection.json"

BG = "#000000"
SURFACE = "#1E1E1E"
FG = "#FFFFFF"
MUTED = "#AAAAAA"


def load_last_uri() -> str:
    try:
        data = json.loads(CONFIG_PATH.read_text())
        return data.get("uri", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def save_last_uri(uri: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"uri": uri}))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.loop = None
        self.task = None
        self.thread = None
        self.connected = False

        root.title("remote-hid")
        root.configure(bg=BG)
        root.geometry("380x180")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        tk.Label(root, text="Phone address", bg=BG, fg=FG).pack(pady=(18, 4))

        self.uri_var = tk.StringVar(value=load_last_uri() or "ws://")
        tk.Entry(
            root,
            textvariable=self.uri_var,
            width=34,
            bg=SURFACE,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
        ).pack(pady=4, ipady=4)

        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(root, textvariable=self.status_var, bg=BG, fg=MUTED).pack(pady=10)

        self.connect_button = tk.Button(
            root,
            text="Connect",
            command=self.toggle,
            width=18,
            bg=SURFACE,
            fg=FG,
            relief=tk.FLAT,
            activebackground="#333333",
            activeforeground=FG,
        )
        self.connect_button.pack(pady=6)

        # The background thread never touches Tkinter directly — it only
        # ever puts messages on this queue. Only _poll_queue, which is
        # scheduled from the main thread on itself, turns messages into
        # actual widget updates. Calling Tkinter methods from another
        # thread is documented as unsafe; an earlier version of this
        # file called root.after() directly from the worker thread and
        # it threw RuntimeError: main thread is not in main loop under
        # real testing — this queue is the fix, not a nicety.
        self.status_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.root.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.status_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "reset_button":
                    self.connected = False
                    self.connect_button.config(text="Connect")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def toggle(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        uri = self.uri_var.get().strip()
        if not (uri.startswith("ws://") or uri.startswith("wss://")):
            self.status_var.set("Address must start with ws:// or wss://")
            return
        save_last_uri(uri)
        self.connected = True
        self.connect_button.config(text="Disconnect")
        self.status_var.set("Connecting...")
        self.thread = threading.Thread(target=self._run, args=(uri,), daemon=True)
        self.thread.start()

    def disconnect(self):
        if self.loop and self.task:
            self.loop.call_soon_threadsafe(self.task.cancel)
        self.connected = False
        self.connect_button.config(text="Connect")

    def _set_status(self, text: str):
        self.status_queue.put(("status", text))

    def _run(self, uri: str):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            backend = UinputBackend()
        except Exception as exc:
            self.status_queue.put(("status", f"Input backend failed: {exc}"))
            self.status_queue.put(("reset_button", None))
            return

        self.task = self.loop.create_task(run_client(uri, backend, on_status=self._set_status))
        try:
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            self.status_queue.put(("status", "Disconnected"))
        except OSError as exc:
            self.status_queue.put(("status", f"Could not connect: {exc}"))
        finally:
            backend.close()
            self.status_queue.put(("reset_button", None))

    def _on_close(self):
        if self.connected:
            self.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
