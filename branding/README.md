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
entry, wired to this checkout's `linux-client/gui.py`. The GUI has its
own address field and remembers the last one you used, so a bare
launch from the app menu now actually works — no arguments needed.
