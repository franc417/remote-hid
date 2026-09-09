# Android app — not started yet

This is next after the Linux client is validated on real hardware.
Planned scope, per `../README.md`'s architecture:

- Touch UI: trackpad (upper half, expandable to full screen) + full
  keyboard (lower half), matching the split-view mockups from the design
  discussion — including sticky Ctrl/Alt/Shift/Fn, an arrow-key cluster,
  and a Fn-toggle for the number row.
- Embedded WebSocket server (e.g. Ktor or NanoWSD) speaking the protocol
  in `../PROTOCOL.md`.
- NSD (Android's mDNS wrapper) service advertisement, plus a QR code
  encoding `{ip, port, pairing_token}` for fast pairing.

No code here yet — intentionally, rather than shipping an unbuilt,
unverified Gradle project. This sandbox has no Android SDK available to
compile or test against, so anything written here now couldn't actually
be verified.
