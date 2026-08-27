#!/usr/bin/env bash
# Vendor the FreeCAD GUI MCP at the commit the design agent audited.
#
# freecad-mcp is third-party (MIT, neka-nat), is not discovered or validated by
# the agent at runtime, and is the component engineers touch most. Pinning a
# fork means upstream changes arrive when you choose them rather than on their
# default branch's schedule.
#
#   ./scripts/vendor-freecad-mcp.sh <destination> [fork-remote-url]
#
# Install it from the resulting checkout, in its own environment, outside the
# agent's — the agent's release boundary requires that separation.

set -euo pipefail

# The audited commit from docs/FREECAD_GUI_MCP_INTEGRATION.md. Upstream's
# declared version (0.1.19) and its lockfile (0.1.17) disagree; the commit is
# the only identity that means anything here.
readonly PINNED_COMMIT="7667e272e1db669ff61dd5411fb4f622691f2dbc"
readonly UPSTREAM="https://github.com/neka-nat/freecad-mcp"

DEST="${1:?usage: vendor-freecad-mcp.sh <destination> [fork-remote-url]}"
FORK="${2:-}"

if [ -e "$DEST" ]; then
  echo "error: $DEST already exists — remove it or choose another path" >&2
  exit 1
fi

git clone "$UPSTREAM" "$DEST"
git -C "$DEST" checkout --detach "$PINNED_COMMIT"

ACTUAL="$(git -C "$DEST" rev-parse HEAD)"
if [ "$ACTUAL" != "$PINNED_COMMIT" ]; then
  echo "error: HEAD is $ACTUAL, expected $PINNED_COMMIT" >&2
  exit 1
fi

if [ -n "$(git -C "$DEST" status --porcelain)" ]; then
  echo "error: checkout is dirty; the agent's release harness requires it clean" >&2
  exit 1
fi

if [ -n "$FORK" ]; then
  git -C "$DEST" remote rename origin upstream
  git -C "$DEST" remote add origin "$FORK"
  git -C "$DEST" checkout -B vendored
  echo
  echo "Push your pinned copy:  git -C $DEST push -u origin vendored"
fi

echo
echo "freecad-mcp vendored at $PINNED_COMMIT"
echo "  $DEST"
echo "Install per upstream's instructions, in an environment separate from the design agent."
