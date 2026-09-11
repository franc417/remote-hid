# Android server app

Runs on the phone: embedded WebSocket server + trackpad/keyboard UI.

## What's built

- `protocol/Protocol.kt` — inbound message validation, mirrors `linux-client/protocol.py`. Pure Kotlin, unit tested with plain JUnit.
- `protocol/Json.kt` — outbound message serialization. Also pure Kotlin, also unit tested with plain JUnit — no Robolectric needed for either.
- `net/WsServer.kt` — the embedded server (NanoWSD). Decodes/validates inbound frames, and now also sends outbound ones via `sendToClient()` to whichever desktop client is currently connected. Android-only (NanoHTTPD + `org.json`), so unverified locally — built and run for the first time by CI, on a real Android SDK + Gradle.
- `input/TrackpadView.kt` — one-finger drag to move, tap to click, two-finger drag to scroll. Now also draws a fading trail of glowing white hexagons following the touch point (pure visual, doesn't affect what's sent).
- `input/KeyboardView.kt` — full layout from the design mockups: number row, three letter rows, sticky Ctrl/Alt/Shift, an escape key, and an arrow cluster. Rounded keys with real press-state feedback. Ctrl/Alt/Fn rest at a lighter grey than regular keys; any armed/active modifier (including Fn) flips to a bright white/black highlight. Fn now actually works — toggles the number row between digits and F1-F10.
- `MainActivity.kt` — wires both views' events to `WsServer.sendToClient()`, split-view layout (trackpad on top, keyboard below), and the expand button that hides the keyboard for a full-screen trackpad and swaps its own label to bring it back.

## What's a known simplification, not a bug

- **`123` is still inert.** No symbol row yet. Fn switching (digits ↔ F1-F10) is now real, though — that part's done.
- **Click-and-drag isn't implemented.** The trackpad sends a plain click (down+up together) on tap; there's no separate press/drag/release sequence yet.
- **Trackpad gesture disambiguation is basic.** A tap right after a two-finger scroll *shouldn't* register as a click (there's a flag guarding this), but this hasn't been tested on a real touchscreen — only reviewed by eye and confirmed to compile.
- **No discovery/pairing.** The IP shown on screen still has to be typed into the Linux client by hand.

## What's genuinely unverified

Everything in `net/` and both custom views under `input/` — this is real touchscreen/UI/rendering code that only a real device can actually exercise. CI proves it *compiles*; it doesn't prove a drag gesture feels right, that the hex glow actually renders (BlurMaskFilter support varies by device/API level, which is why the view forces a software layer), or that two fingers scroll smoothly. That part needs you, on your phone, telling me what's off.

## Build

No Gradle wrapper is committed (nothing here could generate the binary
`gradle-wrapper.jar` without a working local Gradle install). Two ways
to build:

- **Android Studio**: open `android-app/`, let it generate a wrapper on
  first sync, build normally.
- **CLI**: `gradle build` with a local Gradle install matching the
  version in `.github/workflows/android-ci.yml`.

CI builds and unit-tests on every push that touches this directory.
