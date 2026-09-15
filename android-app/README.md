# Android server app

Runs on the phone: embedded WebSocket server + trackpad/keyboard UI.

## What's built

- `protocol/Protocol.kt` — inbound message validation, mirrors `linux-client/protocol.py`. Pure Kotlin, unit tested with plain JUnit.
- `protocol/Json.kt` — outbound message serialization. Also pure Kotlin, also unit tested with plain JUnit — no Robolectric needed for either.
- `net/WsServer.kt` — the embedded server (NanoWSD). Decodes/validates inbound frames, sends outbound ones via `sendToClient()`. Android-only (NanoHTTPD + `org.json`), so unverified locally — built and run for the first time by CI, on a real Android SDK + Gradle.
- `net/RemoteHidService.kt` — **owns the `WsServer` now, not `MainActivity`.** This is a direct fix for a real bug found in actual use: with the server tied to the Activity's `onStart`/`onStop`, backgrounding the app for any reason (screen lock, switching apps) killed the connection outright. The service is foreground (persistent notification, survives the Activity being stopped), and `MainActivity` binds to it only while visible, to wire up UI callbacks — unbinding on `onStop()` does *not* stop the service.
- `input/TrackpadView.kt` — one-finger drag to move, tap to click, two-finger drag to scroll. Draws a small cluster of 3 glowing hexagons orbiting the live touch point, fading out ~250ms after release. Also: a second tap that holds and drags (within 300ms, roughly the same spot) becomes a proper click-and-drag (press, drag, release) for text selection and drag-and-drop — the raw event sequence a real double-click-drag produces, so the receiving OS's own selection heuristics handle the rest. Three-finger swipes: horizontal switches workspace (Ctrl+Alt+Left/Right — confirmed default across GNOME, Cinnamon, MATE, and XFCE, not GNOME-only), vertical opens an app overview (swipe up, Super/Meta alone) or goes back (swipe down, Escape).
- `input/KeyboardView.kt` — full layout from the design mockups, now with bigger keys (56dp rows, up from 42dp) and a dedicated Windows/Super key (`win`, sends Meta as a normal keypress — opens an app launcher/overview on most desktop environments) alongside sticky Ctrl/Alt/Shift, escape, and Print Screen. Fn now covers more than F-keys: it also swaps the arrow cluster to Home/End/PageUp/PageDown, matching how a real laptop's Fn row doubles up arrow keys. Also builds a live local echo of what's being typed (letters/digits/symbols/space append, Backspace removes, Enter clears), exposed via `onPreviewTextChanged` for the typing-preview bar below.
- Typing preview bar (`activity_main.xml`'s `typingPreview`, wired in `MainActivity.kt`) — sits right below the header, hidden until you start typing. This is a reconstruction of which keys were tapped, not a readback of what actually landed in a text field on the desktop (the phone has no way to know that) — useful for confirming what you're sending when you can't see the laptop screen, not for verifying autocomplete/autocorrect happened a particular way on the receiving end.
- QR pairing: `MainActivity.kt`'s scan mode uses CameraX + ML Kit to read a QR code the desktop app displays, then sends this phone's `ws://` address to a rendezvous port encoded in that QR — a one-shot side-channel handshake so the human never has to type an IP. The phone's own WebSocket server is unaffected; this doesn't change who's the server and who's the client.
- `MainActivity.kt` — wires both views' events to `WsServer.sendToClient()`, split-view layout (trackpad on top, keyboard below), and the expand button that hides the keyboard for a full-screen trackpad and swaps its own label to bring it back.

## What's a known simplification, not a bug

- **`123` is still inert.** No symbol row yet.
- **No Settings tab yet, on either app.** QR pairing is wired into the existing screens (a `scan` button on the main phone screen, a QR image in the desktop window) rather than a proper tabbed settings section. Worth doing as its own focused pass rather than folding it into this one.
- **Three-finger gesture thresholds and the vertical-swipe direction are best guesses.** The horizontal workspace-switch shortcut is a confirmed shared default across GNOME, Cinnamon, MATE, and XFCE (see `TrackpadView.kt`'s doc comment) — but the swipe distance needed to trigger it, and whether up/down should map to overview/back specifically, are untested.
- **The QR code the desktop shows never refreshes.** If the desktop's IP changes after launch, restart the app.

## What's genuinely unverified

Everything in `net/` and both custom views under `input/` is real touchscreen/UI/rendering/lifecycle code CI can only prove *compiles*, not that it feels right. The foreground service fix in particular needed real-world confirmation: does the connection survive a screen lock? A first attempt at this crashed outright with `SecurityException: Starting FGS with type connectedDevice ... requires permissions: ... any of [BLUETOOTH_ADVERTISE, ... CHANGE_WIFI_STATE, ...]` — Android 14's `connectedDevice` foreground service type requires holding an unrelated companion permission this app has no real reason for. Switched to `dataSync`, which has no such requirement and is a more honest description of what the service does. Confirmed working after that fix.

A second, more serious crash was then reported and fixed: `NetworkOnMainThreadException` on the very first trackpad touch or key press. `WsServer.sendToClient()` was doing a blocking socket write synchronously on whatever thread called it — which, called directly from touch/click UI callbacks, was always the main thread. Android kills the app outright for network I/O on the main thread. Fixed with a single-thread executor inside `WsServer` so the actual write always happens off the main thread, while still processing sends strictly in order (out-of-order cursor deltas would be worse than an occasional dropped one). Confirmed working after that fix.

A third issue was then reported and fixed: the app worked, but disconnected after ~5 seconds, later ~20s. Root cause, confirmed against NanoHTTPD's own source and multiple independent bug reports describing this exact symptom: `ws.start()` with no arguments uses NanoHTTPD's default `SOCKET_READ_TIMEOUT` (5000ms), applied to the raw socket at accept time and never revisited after the WebSocket upgrade. The desktop's Python `websockets` library runs its own keepalive by default (a Ping on `ping_interval`, dropping the connection if no Pong within `ping_timeout`) — both sides' numbers need to actually agree for this to work. Current values: Android's raw socket timeout is 660 seconds (11 min); the desktop pings every 20s and tolerates up to 600s (10 min) without a Pong before giving up — Android's number is deliberately the larger of the two, so it's never the tighter constraint. Not yet reconfirmed at these exact new values after the ~20s report, though the same mechanism that fixed the 5s case applies directly.

The QR scanning path (CameraX + ML Kit, in `MainActivity.kt`) is still unconfirmed working — it compiles, but "nothing is being scanned from the phone's side" was reported and not yet diagnosed. Needs: does a camera permission prompt appear at all? Does the preview show a live video feed when you tap scan, or does it stay black?

## Build

No Gradle wrapper is committed (nothing here could generate the binary
`gradle-wrapper.jar` without a working local Gradle install). Two ways
to build:

- **Android Studio**: open `android-app/`, let it generate a wrapper on
  first sync, build normally.
- **CLI**: `gradle build` with a local Gradle install matching the
  version in `.github/workflows/android-ci.yml`.

CI builds and unit-tests on every push that touches this directory.
