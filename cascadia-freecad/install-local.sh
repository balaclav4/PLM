#!/usr/bin/env bash
# Install this addon into FreeCAD, locally, with no addon index involved.
#
#   ./install-local.sh            # symlink (default) — edits here take effect on restart
#   ./install-local.sh --copy     # copy instead, for machines where symlinks are awkward
#
# FreeCAD loads every directory under Mod/ at startup and puts it on sys.path,
# which is what makes `import cascadia_bridge` work inside FreeCAD. Nothing here
# talks to the FreeCAD addon index or any server.

set -euo pipefail

ADDON_NAME="CascadiaPLM"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="symlink"
[ "${1:-}" = "--copy" ] && MODE="copy"

# Ask FreeCAD where its user directory is rather than guessing per platform.
# getUserAppDataDir() is the documented location whose Mod/ subdirectory holds
# user addons.
find_freecad() {
  for candidate in freecadcmd FreeCADCmd freecad FreeCAD; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [ -n "${FREECAD_USER_DIR:-}" ]; then
  USER_DIR="$FREECAD_USER_DIR"
  echo "Using FREECAD_USER_DIR: $USER_DIR"
elif FREECAD_BIN="$(find_freecad)"; then
  USER_DIR="$("$FREECAD_BIN" -c "import FreeCAD; print(FreeCAD.getUserAppDataDir())" 2>/dev/null | tail -1 | tr -d '\r')"
  if [ -z "$USER_DIR" ] || [ ! -d "$USER_DIR" ]; then
    echo "error: '$FREECAD_BIN' did not report a usable user directory." >&2
    echo "       Run this in FreeCAD's Python console and re-run with it:" >&2
    echo "         import FreeCAD; FreeCAD.getUserAppDataDir()" >&2
    echo "       FREECAD_USER_DIR=/that/path ./install-local.sh" >&2
    exit 1
  fi
  echo "FreeCAD user directory: $USER_DIR"
else
  echo "error: no FreeCAD executable on PATH." >&2
  echo "       Find the path in FreeCAD's Python console:" >&2
  echo "         import FreeCAD; FreeCAD.getUserAppDataDir()" >&2
  echo "       then: FREECAD_USER_DIR=/that/path ./install-local.sh" >&2
  exit 1
fi

TARGET="${USER_DIR%/}/Mod/$ADDON_NAME"
mkdir -p "$(dirname "$TARGET")"

if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  echo "Replacing existing install at $TARGET"
  rm -rf "$TARGET"
fi

if [ "$MODE" = "symlink" ]; then
  ln -s "$SOURCE" "$TARGET"
  echo "Symlinked $TARGET -> $SOURCE"
  echo "Edits in this checkout take effect when FreeCAD restarts."
else
  mkdir -p "$TARGET"
  # Copy the addon only — tests and scratch files have no business in Mod/.
  for entry in package.xml Init.py InitGui.py pyproject.toml README.md cascadia_bridge agent-tool-contract.json; do
    [ -e "$SOURCE/$entry" ] && cp -r "$SOURCE/$entry" "$TARGET/"
  done
  find "$TARGET" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
  echo "Copied the addon to $TARGET"
fi

cat <<EOF

Installed. Next:
  1. Restart FreeCAD.
  2. Pick "Cascadia PLM" from the workbench selector.
  3. Click "Cascadia PLM status" first — it reports whether this build can dock
     the panel, and where the panel points. No Python console needed.
  4. Then the panel button.

Point the panel at your instance by setting CASCADIA_URL before launching
FreeCAD, e.g.

  CASCADIA_URL=http://your-host:3000
EOF
