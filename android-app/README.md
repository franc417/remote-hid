# Android server app

Runs on the phone: embedded WebSocket server + trackpad/keyboard UI.

## What's built

- `protocol/Protocol.kt` — inbound message validation, mirrors `linux-client/protocol.py`. Pure Kotlin, unit tested with plain JUnit.
- `protocol/Json.kt` — outbound message serialization. Also pure Kotlin, also unit tested with plain JUnit — no Robolectric needed for either.
- `net/WsServer.kt` — the embedded server (NanoWSD). Decodes/validates inbound frames, and now also sends outbound ones via `sendToClient()` to whichever desktop client is currently connected. Android-only (NanoHTTPD + `org.json`), so unverified locally — built and run for the first time by CI, on a real Android SDK + Gradle.
- `input/TrackpadView.kt` — one-finger drag to move, tap to click, two-finger drag to scroll.
- `input/KeyboardView.kt` — full layout from the design mockups: number row, three letter rows, sticky Ctrl/Alt/Shift (tap to arm, applies to the next key, then clears), and an arrow cluster.
- `MainActivity.kt` — wires both views' events to `WsServer.sendToClient()`, split-view layout (trackpad on top, keyboard below), and the expand button that hides the keyboard for a full-screen trackpad and swaps its own label to bring it back.

## What's a known simplification, not a bug

- **`Fn` and `123` keys are inert.** They're drawn and tappable but do nothing yet — no F-row swap, no symbol row. Both need matching support added to `linux-client/input_backend.py`'s `KEY_MAP` too before they'd mean anything end to end.
- **Click-and-drag isn't implemented.** The trackpad sends a plain click (down+up together) on tap; there's no separate press/drag/release sequence yet.
- **Trackpad gesture disambiguation is basic.** A tap right after a two-finger scroll *shouldn't* register as a click (there's a flag guarding this), but this hasn't been tested on a real touchscreen — only reviewed by eye and confirmed to compile.
- **No discovery/pairing.** The IP shown on screen still has to be typed into the Linux client by hand.

## What's genuinely unverified

Everything in `net/` and the two custom views under `input/` — this is real touchscreen/UI code that only a real device can actually exercise. CI proves it *compiles*; it doesn't prove a drag gesture feels right or that two fingers scroll smoothly. That part needs you, on your phone, telling me what's off.

## Build

No Gradle wrapper is committed (nothing here could generate the binary
`gradle-wrapper.jar` without a working local Gradle install). Two ways
to build:

- **Android Studio**: open `android-app/`, let it generate a wrapper on
  first sync, build normally.
- **CLI**: `gradle build` with a local Gradle install matching the
  version in `.github/workflows/android-ci.yml`.

CI builds and unit-tests on every push that touches this directory.
