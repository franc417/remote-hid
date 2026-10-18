#!/usr/bin/env bash
# Installs a `remote-hid` command and an app-menu entry for the desktop GUI, so
# it starts with one word (or one click) instead of `cd .../linux-client` and
# `python3 gui.py`. No root needed: everything goes under your home directory.
#
#   ./install.sh                       use the active venv's python, else python3
#   ./install.sh --python /path/to/python   bake in a specific interpreter
#   ./install.sh --add-to-path         also add ~/.local/bin to your shell's PATH
#   ./install.sh --uninstall           remove what this script installed
#
# Run it as your NORMAL user (not root, not sudo): it installs into your home
# directory, and your desktop session only looks in your own home.
# If "./install.sh" says "Permission denied", run:  bash install.sh
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
ADD_TO_PATH=0
ALLOW_ROOT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PYTHON="${2:-}"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    --add-to-path) ADD_TO_PATH=1; shift ;;
    --allow-root) ALLOW_ROOT=1; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Root would install into /root, which the desktop user never sees (no menu entry,
# no command). Cleaning up (--uninstall) is still allowed so a mistake can be undone.
if [ "${REMOTE_HID_TEST_UID:-$(id -u)}" = 0 ] && [ "$ALLOW_ROOT" = 0 ] && [ "$UNINSTALL" = 0 ]; then
  echo "Don't run this as root: it would install into $HOME, and your normal desktop user can't see that." >&2
  echo "Leave the root shell (type: exit), then as your normal user run:  bash install.sh" >&2
  echo "(If you already ran it as root, undo that with:  bash install.sh --uninstall)" >&2
  exit 1
fi

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
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
if [ "$ADD_TO_PATH" = 1 ]; then
  case "$(basename "${SHELL:-}")" in
    zsh) RC="$HOME/.zshrc" ;;
    bash) RC="$HOME/.bashrc" ;;
    fish) RC="" ;;
    *) RC="$HOME/.profile" ;;
  esac
  if [ -z "$RC" ]; then
    echo "fish shell: run  fish_add_path ~/.local/bin  (this script does not edit fish's config)"
  elif grep -qsF "$PATH_LINE" "$RC"; then
    echo "$RC already puts ~/.local/bin on your PATH."
  else
    printf '\n# added by remote-hid install.sh\n%s\n' "$PATH_LINE" >> "$RC"
    echo "Added ~/.local/bin to your PATH in $RC. Open a new terminal (or run: source $RC) to use it."
  fi
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "Run it with:  remote-hid" ;;
  *) if [ "$ADD_TO_PATH" = 0 ]; then
       echo "~/.local/bin is not on your PATH, so the word remote-hid won't work yet. Either:"
       echo "  re-run:  bash install.sh --add-to-path     (then open a new terminal)"
       echo "  or add this line to your shell's rc file:  $PATH_LINE"
     fi
     echo "Without that, run it with:  $LAUNCHER   (the app-menu entry works right away)" ;;
esac
