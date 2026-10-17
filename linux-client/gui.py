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
from protocol import SessionReplaced
from reconnect import backoff_delay, candidates, load_known, prioritize, remember, scan_subnet

CONFIG_PATH = Path.home() / ".config" / "remote-hid" / "last_connection.json"
RENDEZVOUS_PORT = 8766

BG = "#000000"
SURFACE = "#1E1E1E"
FG = "#FFFFFF"
MUTED = "#AAAAAA"


def known_path() -> Path:
    """Remembered-phones file, next to CONFIG_PATH. Resolved at call time
    (not import time) so tests that point CONFIG_PATH at a temp dir move
    this with it instead of writing into the real ~/.config."""
    return CONFIG_PATH.with_name("known_devices.json")


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


class Session:
    """State of ONE connection thread. Kept per session (not on App) so that
    when a new connection replaces an old one -- scanning a different phone,
    pressing Connect again -- the old thread winding down can't cancel the
    new one's task, reset its button, or overwrite its status. Messages the
    thread posts carry its Session; the GUI ignores any from a stale one."""

    def __init__(self):
        self.stop = threading.Event()  # set to end this session's reconnect loop, not just one attempt
        self.loop = None
        self.task = None
        self.target = None  # the address actually connected, once it is


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.session = None
        self.thread = None
        self.connected = False
        self.auto_reconnect = True

        root.title("remote-hid")
        root.configure(bg=BG)
        root.geometry("380x450")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        tk.Label(root, text="Phone address", bg=BG, fg=FG).pack(pady=(18, 4))

        self.uri_var = tk.StringVar(value=(load_known(known_path(), CONFIG_PATH) or [""])[0] or "ws://")
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

        # A plain attribute mirrors the checkbox: the connection thread reads
        # it, and Tk variables must only be touched from the main thread.
        self.auto_var = tk.BooleanVar(value=True)
        self.auto_var.trace_add("write", lambda *_: setattr(self, "auto_reconnect", self.auto_var.get()))
        tk.Checkbutton(
            root,
            text="Reconnect automatically",
            variable=self.auto_var,
            bg=BG,
            fg=FG,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=FG,
            highlightthickness=0,
        ).pack(pady=(0, 2))

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
        self._poll_job = self.root.after(100, self._poll_queue)

        self._show_qr()
        threading.Thread(target=self._run_rendezvous, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload, sess = self.status_queue.get_nowait()
                if sess is not None and sess is not self.session:
                    continue  # from a connection that has since been replaced
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "reset_button":
                    self.connected = False
                    self.connect_button.config(text="Connect")
                elif kind == "announced_uri":
                    current = self.session.target if self.session else None
                    if self.connected and payload == current:
                        continue  # scanned the phone we are already connected to
                    self.uri_var.set(payload)
                    # Connected to a different phone (or still connecting):
                    # scanning another one means "switch", so connect()
                    # ends the old session cleanly first.
                    self.connect()
        except queue.Empty:
            pass
        self._poll_job = self.root.after(100, self._poll_queue)

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
            self.status_queue.put(("status", f"Rendezvous listener failed: {exc}", None))
            return

        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                data = conn.recv(200).decode("utf-8", errors="replace").strip()
            if data.startswith("ws://") or data.startswith("wss://"):
                self.status_queue.put(("announced_uri", data, None))

    def toggle(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def autostart(self):
        """At launch, go straight to the most recent phone that has connected
        before, and keep trying until it's there. Called from main() only, not
        from __init__, so constructing an App (as the tests do) never opens a
        connection on its own."""
        if not self.auto_reconnect or self.connected:
            return
        known = load_known(known_path(), CONFIG_PATH)
        if not known:
            return
        self.uri_var.set(known[0])
        self.connect(persistent=True)

    def connect(self, persistent: bool = False):
        uri = self.uri_var.get().strip()
        if not is_valid_ws_uri(uri):
            self.status_var.set("Enter a full address, e.g. ws://192.168.1.5:8765")
            return
        self._end_session()  # switching phones / reconnecting: drop the old one cleanly first
        session = Session()
        self.session = session
        self.connected = True
        self.connect_button.config(text="Disconnect")
        self.status_var.set("Connecting...")
        self.thread = threading.Thread(target=self._run, args=(uri, persistent, session), daemon=True)
        self.thread.start()

    def _end_session(self):
        """Stops the current session's reconnect loop and cancels whatever
        connection attempt or live connection it has. Safe if there is none."""
        old = self.session
        if old is None:
            return
        old.stop.set()
        if old.loop is not None and old.task is not None:
            try:
                old.loop.call_soon_threadsafe(old.task.cancel)
            except RuntimeError:
                pass  # its loop already finished: nothing left to cancel

    def disconnect(self):
        self._end_session()
        self.connected = False
        self.connect_button.config(text="Connect")

    def _set_status(self, text: str, session: "Session"):
        self.status_queue.put(("status", text, session))

    def _run(self, uri: str, persistent: bool = False, session: "Session" = None):
        session = session or Session()
        session.loop = asyncio.new_event_loop()
        loop = session.loop
        asyncio.set_event_loop(loop)

        try:
            backend = UinputBackend()
        except Exception as exc:
            self.status_queue.put(("status", f"Input backend failed: {exc}", session))
            self.status_queue.put(("reset_button", None, session))
            return

        def scan():
            ip = local_ip()
            return [] if ip.startswith("127.") else scan_subnet(ip)

        # Retrying only happens once a connection has actually worked in this
        # session (or when launched via autostart with a remembered phone). A
        # first attempt at a mistyped address still fails once and stops, the
        # way it always did, instead of retrying a typo forever.
        primary = uri
        attempt = 0
        ever_connected = False
        reason = ""
        replaced = False
        try:
            while True:
                connected_here = False
                targets = candidates(primary, load_known(known_path(), CONFIG_PATH), attempt,
                                     scan if self.auto_reconnect else None)
                if persistent or attempt > 0 or ever_connected:
                    # Retry rounds: put addresses that answer right now first, so a
                    # stale one (USB gateway after the cable is gone, an old lease)
                    # does not cost a connect timeout before the live one is tried.
                    targets = prioritize(targets)
                for target in targets:
                    if session.stop.is_set():
                        break
                    state = {"up": False}

                    def on_status(text, target=target, state=state):
                        if text.startswith("Connected"):
                            state["up"] = True
                            session.target = target
                            remember(target, known_path(), CONFIG_PATH)  # only a phone that really connected
                        self._set_status(text, session)

                    session.task = loop.create_task(run_client(target, backend, on_status=on_status))
                    try:
                        loop.run_until_complete(session.task)
                    except asyncio.CancelledError:
                        session.stop.set()
                        self.status_queue.put(("status", "Disconnected", session))
                    except SessionReplaced:
                        # The phone gave our session to a newer connection (another
                        # desktop, or a scan from another window). Reconnecting would
                        # just take it back and the two would fight, so stop here and
                        # say why; Connect takes it back on purpose.
                        replaced = True
                        session.stop.set()
                        self.status_queue.put(("status", "Another device took over this phone. Press Connect to take it back.", session))
                    except OSError as exc:
                        reason = f"Could not connect: {exc}"
                        self.status_queue.put(("status", reason, session))
                    except Exception as exc:
                        # Deliberately broad: this is the fix for a real, observed
                        # bug. websockets.exceptions.ConnectionClosedError (phone
                        # dropped the connection, e.g. the app got backgrounded)
                        # isn't a CancelledError or an OSError, so it fell through
                        # both specific handlers uncaught. The finally block below
                        # still reset the button correctly either way (finally
                        # always runs) -- but the status text was never told the
                        # connection had actually died, so it kept showing stale
                        # "Connected to ..." text while nothing was connected. This
                        # catch-all is what actually fixes that: every failure mode
                        # now updates status to something true, not just the two
                        # anticipated ones.
                        reason = f"Connection lost: {exc}"
                        self.status_queue.put(("status", reason, session))
                    if state["up"]:
                        ever_connected = connected_here = True
                        primary = target  # the one that worked leads the next round
                        break
                    if session.stop.is_set():
                        break

                if session.stop.is_set() or not self.auto_reconnect or not (persistent or ever_connected):
                    break
                if connected_here:
                    attempt = 0
                delay = backoff_delay(attempt)
                attempt += 1
                prefix = f"{reason}. " if reason else "Connection closed. "
                self.status_queue.put(("status", f"{prefix}Retrying in {delay:.0f}s...", session))
                if session.stop.wait(delay):
                    break
            if session.stop.is_set() and not replaced:
                self.status_queue.put(("status", "Disconnected", session))
        finally:
            backend.close()
            self.status_queue.put(("reset_button", None, session))

    def _on_close(self):
        if self.connected:
            self.disconnect()
        # Explicitly cancelled rather than relying on destroy() to
        # implicitly clean it up: a real, reproducible test failure
        # showed a stale scheduled after() callback from a destroyed
        # instance colliding with a new one — CPython reused the same
        # memory address for a new App, and Tkinter's auto-generated
        # Tcl command name for the callback (tied to that address) then
        # collided between the two, breaking the new instance's queue
        # polling ("invalid command name ..._poll_queue"). Only turned
        # up under pytest running many Tk() instances in one process in
        # quick succession — unlikely in normal single-instance use,
        # but a real resource-cleanup gap regardless of how it surfaced.
        self.root.after_cancel(self._poll_job)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    app.autostart()
    root.mainloop()


if __name__ == "__main__":
    main()
