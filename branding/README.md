# Branding

- `logo.svg` — master vector source. Edit this, then regenerate everything else.
- `generate-icons.sh` — regenerates the Android launcher icon set and `logo-256.png` from `logo.svg`. Run it after any edit to the source:

  ```bash
  ./generate-icons.sh
  ```

  Requires `rsvg-convert`:
  - Arch: `sudo pacman -S librsvg`
  - Debian/Ubuntu: `sudo apt install librsvg2-bin`

- `logo-256.png` — general-purpose PNG (README badges, etc.), generated, not hand-edited.
- `remote-hid.desktop` — Linux launcher entry template for the client.

## Installing the desktop icon (optional)

```bash
./generate-icons.sh --install-desktop-icon
```

Copies the SVG into your user icon theme and installs the `.desktop`
entry, wired to this checkout's `linux-client/client.py`. Honest caveat:
the client currently requires a `ws://<ip>:<port>` argument to do
anything, so launching from an app menu today just opens a terminal
showing the usage message — this is here for the icon/branding
plumbing now, ahead of the client having something like a "last
connected phone" default to actually make a bare launch useful.
