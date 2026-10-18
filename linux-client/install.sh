#!/usr/bin/env bash
# Installs a `remote-hid` command and an app-menu entry for the desktop GUI, so
# it starts with one word (or one click) instead of `cd .../linux-client` and
# `python3 gui.py`. No root needed: everything goes under your home directory.
#
#   ./install.sh                       use the active venv's python, else python3
#   ./install.sh --python /path/to/python   bake in a specific interpreter
#   ./install.sh --uninstall           remove what this script installed
#
# The launcher runs gui.py in THIS checkout, so `git pull` is all an update needs.

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
LAUNCHER="$BIN_DIR/remote-hid"
DESKTOP="$DATA_DIR/applications/remote-hid.desktop"
ICON="$DATA_DIR/icons/hicolor/256x256/apps/remote-hid.png"
LOGO="$HERE/../branding/logo-256.png"

PYTHON=""
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PYTHON="${2:-}"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

if [ "$UNINSTALL" = 1 ]; then
  rm -f "$LAUNCHER" "$DESKTOP" "$ICON"
  echo "Removed remote-hid launcher, menu entry and icon."
  exit 0
fi

# Which python: explicit flag, else the active virtualenv, else python3 on PATH.
if [ -z "$PYTHON" ]; then
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
  else
    PYTHON="$(command -v python3 || true)"
  fi
fi
if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
  echo "Could not find a python to use (${PYTHON:-none}). Pass one with --python /path/to/python." >&2
  exit 1
fi
PYTHON="$(cd "$(dirname "$PYTHON")" && pwd)/$(basename "$PYTHON")"  # absolute, so the launcher works from anywhere

# Check the GUI's imports with that python and say exactly what is missing.
MISSING="$("$PYTHON" - <<'PY' 2>/dev/null || echo "?"
import importlib
missing = []
for mod, label in (("tkinter", "tkinter"), ("websockets", "websockets"), ("qrcode", "qrcode"),
                   ("PIL.ImageTk", "pillow (ImageTk)"), ("evdev", "evdev")):
    try:
        importlib.import_module(mod)
    except Exception:
        missing.append(label)
print(", ".join(missing))
PY
)"
if [ "$MISSING" = "?" ]; then
  echo "Warning: could not run $PYTHON to check its packages." >&2
elif [ -n "$MISSING" ]; then
  echo "Warning: $PYTHON is missing: $MISSING" >&2
  echo "  pip install websockets qrcode pillow evdev   (tkinter comes from your distro: python3-tk / tk)" >&2
fi

mkdir -p "$BIN_DIR" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"

cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
# Written by $HERE/install.sh: re-run it to change the python or the checkout.
exec "$PYTHON" "$HERE/gui.py" "\$@"
LAUNCH
chmod +x "$LAUNCHER"

if [ -f "$LOGO" ]; then
  cp "$LOGO" "$ICON"
fi

cat > "$DESKTOP" <<ENTRY
[Desktop Entry]
Type=Application
Name=remote-hid
Comment=Wireless trackpad and keyboard client
Exec=$LAUNCHER
Icon=remote-hid
Terminal=false
Categories=Utility;
ENTRY

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$(dirname "$DESKTOP")" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA_DIR/icons/hicolor" 2>/dev/null || true

echo "Installed:"
echo "  command    $LAUNCHER"
echo "  menu entry $DESKTOP"
echo "  python     $PYTHON"
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "Run it with:  remote-hid" ;;
  *) echo "Add $BIN_DIR to your PATH (e.g. in ~/.bashrc or ~/.zshrc):  export PATH=\"\$HOME/.local/bin:\$PATH\""
     echo "Until then run it with:  $LAUNCHER" ;;
esac
