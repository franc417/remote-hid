#!/usr/bin/env bash
# Regenerates every icon size from branding/logo.svg — the Android
# mipmap set, the 256px general-purpose PNG, and (optionally) installs
# the Linux desktop icon + launcher entry.
#
# Run from anywhere; it finds the repo root relative to this script.
#
# Requires rsvg-convert:
#   Arch:          sudo pacman -S librsvg
#   Debian/Ubuntu: sudo apt install librsvg2-bin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SVG="$SCRIPT_DIR/logo.svg"

if ! command -v rsvg-convert >/dev/null 2>&1; then
  echo "rsvg-convert not found." >&2
  echo "Arch:          sudo pacman -S librsvg" >&2
  echo "Debian/Ubuntu: sudo apt install librsvg2-bin" >&2
  exit 1
fi

echo "Generating Android launcher icons..."
declare -A DENSITIES=( [mdpi]=48 [hdpi]=72 [xhdpi]=96 [xxhdpi]=144 [xxxhdpi]=192 )
for density in "${!DENSITIES[@]}"; do
  size="${DENSITIES[$density]}"
  outdir="$REPO_ROOT/android-app/app/src/main/res/mipmap-${density}"
  mkdir -p "$outdir"
  rsvg-convert -w "$size" -h "$size" "$SVG" -o "$outdir/ic_launcher.png"
  echo "  mipmap-${density} (${size}x${size})"
done

echo "Generating general-purpose PNG..."
rsvg-convert -w 256 -h 256 "$SVG" -o "$SCRIPT_DIR/logo-256.png"

# --- Optional: install as a Linux desktop icon for the client ---
if [ "${1:-}" = "--install-desktop-icon" ]; then
  ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
  DESKTOP_DIR="$HOME/.local/share/applications"
  mkdir -p "$ICON_DIR" "$DESKTOP_DIR"
  cp "$SVG" "$ICON_DIR/remote-hid.svg"
  cp "$SCRIPT_DIR/remote-hid.desktop" "$DESKTOP_DIR/remote-hid.desktop"
  # Point Exec at this checkout's client.py rather than a hardcoded path
  sed -i "s|__CLIENT_PATH__|$REPO_ROOT/linux-client/client.py|" "$DESKTOP_DIR/remote-hid.desktop"
  update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
  gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
  echo "Installed desktop icon + launcher entry (icon theme cache may take a moment to refresh)."
fi

echo "Done."
