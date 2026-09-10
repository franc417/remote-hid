# Android server app

Runs on the phone: embedded WebSocket server + trackpad/keyboard UI.

## Status

- `protocol/Protocol.kt` — message validation, mirrors `linux-client/protocol.py`. Pure Kotlin, no Android dependency, unit tested with plain JUnit (`app/src/test/`).
- `net/WsServer.kt` — the actual embedded server, built on NanoWSD. Decodes JSON frames, validates them, hands them off. This is Android-only code (NanoHTTPD + `org.json`), so it has **not** been verified locally — there's no Android SDK in the sandbox this was written in. It's built for the first time by CI (`.github/workflows/android-ci.yml`), on a real GitHub Actions runner with a real JDK, Android SDK, and Gradle.
- `MainActivity.kt` — starts/stops the server with the activity lifecycle, shows connection status and the phone's local IP so it can be typed into the Linux client for now (no discovery/pairing yet).

## What's not here yet

- The actual trackpad/keyboard touch UI from the design mockups (split view, sticky modifiers, arrow cluster) — this app currently just shows connection status.
- NSD/mDNS discovery and QR pairing.
- Wiring `onMessage` to anything — right now the server validates and receives messages but doesn't act on them, because this device *is* the server; there's nothing to inject input into locally. (The Linux client is the one that does that, on the other end of the connection.)
- A foreground service to keep the server alive when the app isn't in the foreground.

## Build

No Gradle wrapper is committed (nothing here could generate the binary
`gradle-wrapper.jar` without a working local Gradle install). Two ways
to build:

- **Android Studio**: open `android-app/`, let it generate a wrapper on
  first sync, build normally.
- **CLI**: `gradle build` with a local Gradle install matching the
  version in `.github/workflows/android-ci.yml`.

CI builds and unit-tests on every push that touches this directory.
