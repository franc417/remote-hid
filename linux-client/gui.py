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
import socket
import threading
import tkinter as tk
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from PIL import ImageTk

from client import run_client
from input_backend import UinputBackend

CONFIG_PATH = Path.home() / ".config" / "remote-hid" / "last_connection.json"
RENDEZVOUS_PORT = 8766

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


def local_ip() -> str:
    """Best-effort guess at this machine's LAN IP, for the QR code.
    Doesn't actually send anything — connect() on a UDP socket just
    picks the outbound interface so we can read its address back.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def is_valid_ws_uri(uri: str) -> bool:
    """Checks for an actual host, not just the ws:// prefix.

    Real bug this fixes: the address field defaults to the bare text
    "ws://" (no host). That starts with "ws://" trivially, so a plain
    prefix check let it through, and it crashed a background thread
    with websockets.exceptions.InvalidURI — caught live, from an actual
    run, not found by inspection.
    """
    parsed = urlparse(uri)
    return parsed.scheme in ("ws", "wss") and bool(parsed.hostname)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.loop = None
        self.task = None
        self.thread = None
        self.connected = False

        root.title("remote-hid")
        root.configure(bg=BG)
        root.geometry("380x420")
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

        tk.Label(root, text="or scan with the phone", bg=BG, fg=MUTED).pack(pady=(14, 4))
        self.qr_label = tk.Label(root, bg=BG)
        self.qr_label.pack(pady=4)
        self._qr_photo = None  # kept alive here — Tkinter drops images with no live reference

        # The background threads (rendezvous listener, and later the
        # connection thread) never touch Tkinter directly — they only
        # ever put messages on this queue. Only _poll_queue, which is
        # scheduled from the main thread on itself, turns messages into
        # actual widget updates. Calling Tkinter methods from another
        # thread is documented as unsafe; an earlier version of this
        # file called root.after() directly from a worker thread and it
        # threw RuntimeError: main thread is not in main loop under real
        # testing — this queue is the fix, not a nicety. Must exist
        # before any thread that might use it starts — an earlier
        # version of *this* addition started the rendezvous thread
        # first and hit a real AttributeError race under testing.
        self.status_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.root.after(100, self._poll_queue)

        self._show_qr()
        threading.Thread(target=self._run_rendezvous, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.status_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "reset_button":
                    self.connected = False
                    self.connect_button.config(text="Connect")
                elif kind == "announced_uri":
                    self.uri_var.set(payload)
                    if not self.connected:
                        self.connect()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _show_qr(self):
        payload = f"{local_ip()}:{RENDEZVOUS_PORT}"
        img = qrcode.make(payload, border=2).resize((180, 180))
        self._qr_photo = ImageTk.PhotoImage(img)
        self.qr_label.config(image=self._qr_photo)

    def _run_rendezvous(self):
        """Listens for a phone announcing its address after scanning
        this window's QR code, then auto-fills and auto-connects.
        Runs for the app's lifetime — accepts announces one at a time,
        forever, so re-scanning later (e.g. after a disconnect) works
        too. Only ever touches the queue, never Tkinter directly, same
        rule as _run().
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", RENDEZVOUS_PORT))
            srv.listen(1)
        except OSError as exc:
            self.status_queue.put(("status", f"Rendezvous listener failed: {exc}"))
            return

        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                data = conn.recv(200).decode("utf-8", errors="replace").strip()
            if data.startswith("ws://") or data.startswith("wss://"):
                self.status_queue.put(("announced_uri", data))

    def toggle(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        uri = self.uri_var.get().strip()
        if not is_valid_ws_uri(uri):
            self.status_var.set("Enter a full address, e.g. ws://192.168.1.5:8765")
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
        except Exception as exc:
            # Deliberately broad: this is the fix for a real, observed
            # bug. websockets.exceptions.ConnectionClosedError (phone
            # dropped the connection, e.g. the app got backgrounded)
            # isn't a CancelledError or an OSError, so it fell through
            # both specific handlers uncaught. The finally block below
            # still reset the button correctly either way (finally
            # always runs) — but the status text was never told the
            # connection had actually died, so it kept showing stale
            # "Connected to ..." text while nothing was connected. This
            # catch-all is what actually fixes that: every failure mode
            # now updates status to something true, not just the two
            # anticipated ones.
            self.status_queue.put(("status", f"Connection lost: {exc}"))
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
