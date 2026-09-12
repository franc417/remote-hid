# Android server app

Runs on the phone: embedded WebSocket server + trackpad/keyboard UI.

## What's built

- `protocol/Protocol.kt` — inbound message validation, mirrors `linux-client/protocol.py`. Pure Kotlin, unit tested with plain JUnit.
- `protocol/Json.kt` — outbound message serialization. Also pure Kotlin, also unit tested with plain JUnit — no Robolectric needed for either.
- `net/WsServer.kt` — the embedded server (NanoWSD). Decodes/validates inbound frames, sends outbound ones via `sendToClient()`. Android-only (NanoHTTPD + `org.json`), so unverified locally — built and run for the first time by CI, on a real Android SDK + Gradle.
- `net/RemoteHidService.kt` — **owns the `WsServer` now, not `MainActivity`.** This is a direct fix for a real bug found in actual use: with the server tied to the Activity's `onStart`/`onStop`, backgrounding the app for any reason (screen lock, switching apps) killed the connection outright. The service is foreground (persistent notification, survives the Activity being stopped), and `MainActivity` binds to it only while visible, to wire up UI callbacks — unbinding on `onStop()` does *not* stop the service.
- `input/TrackpadView.kt` — one-finger drag to move, tap to click, two-finger drag to scroll. Draws a small cluster of 3 glowing hexagons orbiting the live touch point (not a historical trail), fading out ~250ms after release.
- `input/KeyboardView.kt` — full layout from the design mockups: number row (with `-`/`=`, doubling as F11/F12 under Fn), three letter rows, sticky Ctrl/Alt/Shift, an escape key, a Print Screen key, and an arrow cluster. Rounded keys with real press-state feedback, fixed-height rows so keys stay close to square rather than stretching to fill available space. Ctrl/Alt/Fn rest at a lighter grey; any armed/active modifier (including Fn) flips to a bright white/black highlight. Fn toggles the whole number row between digits/-/= and F1-F12.
- QR pairing: `MainActivity.kt`'s scan mode uses CameraX + ML Kit to read a QR code the desktop app displays, then sends this phone's `ws://` address to a rendezvous port encoded in that QR — a one-shot side-channel handshake so the human never has to type an IP. The phone's own WebSocket server is unaffected; this doesn't change who's the server and who's the client.
- `MainActivity.kt` — wires both views' events to `WsServer.sendToClient()`, split-view layout (trackpad on top, keyboard below), and the expand button that hides the keyboard for a full-screen trackpad and swaps its own label to bring it back.

## What's a known simplification, not a bug

- **`123` is still inert.** No symbol row yet.
- **No Settings tab yet, on either app.** QR pairing is wired into the existing screens (a `scan` button on the main phone screen, a QR image in the desktop window) rather than a proper tabbed settings section. Worth doing as its own focused pass rather than folding it into this one.
- **Click-and-drag isn't implemented.** The trackpad sends a plain click (down+up together) on tap; there's no separate press/drag/release sequence yet.
- **Trackpad gesture disambiguation is basic.** A tap right after a two-finger scroll *shouldn't* register as a click (there's a flag guarding this), but this hasn't been tested on a real touchscreen — only reviewed by eye and confirmed to compile.
- **The QR code the desktop shows never refreshes.** If the desktop's IP changes after launch, restart the app.

## What's genuinely unverified

Everything in `net/` and both custom views under `input/` is real touchscreen/UI/rendering/lifecycle code CI can only prove *compiles*, not that it feels right. The foreground service fix in particular needs real-world confirmation: does the connection actually survive a screen lock now? A first attempt at this crashed outright with `SecurityException: Starting FGS with type connectedDevice ... requires permissions: ... any of [BLUETOOTH_ADVERTISE, ... CHANGE_WIFI_STATE, ...]` — Android 14's `connectedDevice` foreground service type requires holding an unrelated companion permission this app has no real reason for. Switched to `dataSync`, which has no such requirement and is a more honest description of what the service does. That specific crash should be gone, but needs confirming on your phone — I have no Android runtime to verify it against.

A second, more serious crash was then reported and fixed: `NetworkOnMainThreadException` on the very first trackpad touch or key press. `WsServer.sendToClient()` was doing a blocking socket write synchronously on whatever thread called it — which, called directly from touch/click UI callbacks, was always the main thread. Android kills the app outright for network I/O on the main thread. Fixed with a single-thread executor inside `WsServer` so the actual write always happens off the main thread, while still processing sends strictly in order (out-of-order cursor deltas would be worse than an occasional dropped one). This was the connection being killed by a crash, not a clean disconnect — "no close frame sent or received" in the report matches that exactly.

A third issue was then reported: the app worked, but disconnected after ~5 seconds. Root cause, confirmed against NanoHTTPD's own source and multiple independent bug reports describing this exact symptom: `ws.start()` with no arguments uses NanoHTTPD's default `SOCKET_READ_TIMEOUT` (5000ms), applied to the raw socket at accept time and never revisited after the WebSocket upgrade. The desktop's Python `websockets` library already runs its own correct keepalive by default (a Ping every 20s, dropping the connection if no Pong within 20s) — the actual bug was that Android's 5s timeout was shorter than even that 20s cadence, so the two mechanisms were never compatible regardless of network conditions. Fixed by calling `ws.start(60_000, false)` instead — 3x margin over the desktop's 20s ping interval — rather than building a redundant Android-side ping scheduler on top of a client-side mechanism that already does this correctly. `client.py` now also sets `ping_interval`/`ping_timeout` explicitly (still 20/20, matching the library's current defaults) so the relationship between the two sides' numbers is documented in code rather than resting on both sides' defaults happening to agree.

The QR scanning path (CameraX + ML Kit, in `MainActivity.kt`) is still unconfirmed working — it compiles, but "nothing is being scanned from the phone's side" was reported and not yet diagnosed. Needs: does a camera permission prompt appear at all? Does the preview show a live video feed when you tap scan, or does it stay black? That'll narrow down whether it's a permission issue, a preview-binding issue, or a detection issue.

## Build

No Gradle wrapper is committed (nothing here could generate the binary
`gradle-wrapper.jar` without a working local Gradle install). Two ways
to build:

- **Android Studio**: open `android-app/`, let it generate a wrapper on
  first sync, build normally.
- **CLI**: `gradle build` with a local Gradle install matching the
  version in `.github/workflows/android-ci.yml`.

CI builds and unit-tests on every push that touches this directory.
