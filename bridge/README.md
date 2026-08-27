# cascadia-bridge

The FCStd round-trip between Cascadia PLM's file vault and the AI Mechanical
3DCAD Design Agent. A file leaves the vault into a design-job working copy and
comes back as a new version, carrying enough identity in both directions that
the check-in can prove which vault version the work descends from.

It is a client of two APIs, not a change to either system. Cascadia never opens
an FCStd; the agent never writes to Cascadia's database.

## Install

No third-party dependencies — it has to install cleanly alongside the design
agent without dragging an HTTP stack in behind it.

```bash
pip install -e bridge          # Python 3.12+
```

## Use

```bash
export CASCADIA_URL=http://localhost:3000
export CASCADIA_API_KEY=csc_...        # Cascadia → Settings → API Keys

cascadia-bridge checkout <file-id> --into ./job-workspace --eco <eco-id> --job <job-id>
# ... the agent and FreeCAD work on ./job-workspace/<name>.FCStd ...
cascadia-bridge status  --from ./job-workspace
cascadia-bridge checkin --from ./job-workspace --message "fillet added"
```

`checkout` writes a `.cascadia-bridge.json` sidecar next to the file recording
the vault file id, item id, version, SHA-256 at checkout, and the ECO and job
ids. `checkin` reads it back, compares digests, and mints a new version only if
the bytes actually changed.

## Before you build on any of this

Two preflight questions decide whether the integration is viable at all.

**Will the agent accept your models?** It refuses scripted FreeCAD documents —
`App::FeaturePython`, Python proxies, Python-object properties — before FreeCAD
opens the archive. Assembly4, the fasteners workbench and most parametric addons
persist exactly those types, so a library built with them is rejected wholesale.
This is not configurable: the check _is_ the agent's trust boundary.

```bash
fcstd-scan /path/to/model/library --agent-src /path/to/agent/src
# Scanned 214 models — 176 accepted, 38 refused (82.2% usable)
```

The scanner imports the agent's own `fcstd_security` module and calls the same
function the agent calls, so its verdict is the real one rather than an
approximation. Without an agent checkout it falls back to a cruder check and
says so; `--require-agent` refuses to guess. Run this before anything else — a
low acceptance rate changes the project.

**Is the environment the one the agent certified?**

```bash
cascadia-preflight freecad /path/to/FreeCADCmd --expect-sha256 <digest>
cascadia-preflight contract /path/to/agent/src --snapshot bridge/agent-tool-contract.json
```

The first checks the binary against version 1.1.3 and its reviewed digest — the
agent blocks anything else outright. The second diffs the agent's 78 MCP tools
against the recorded snapshot, so an upstream rename fails a check instead of
failing a design session. New tools are fine; a removed one is not.

To vendor the third-party FreeCAD GUI MCP at the commit the agent audited:

```bash
./scripts/vendor-freecad-mcp.sh ../freecad-mcp [your-fork-url]
```

## Cascadia inside the FreeCAD window

`freecad/CascadiaPanel.py` puts Cascadia's UI in a dock panel beside the 3D view
(or an MDI tab), so the part, its BOM and its change order are on one screen
instead of behind an alt-tab.

```python
import CascadiaPanel
CascadiaPanel.show()                    # dock panel, remembers where you put it
CascadiaPanel.show(as_tab=True)         # MDI tab next to the 3D view
CascadiaPanel.show_part(part_id)        # deep-link
CascadiaPanel.show_working_copy(workdir)  # follow a bridge checkout to its record
```

Two things worth knowing before you rely on it:

- **The Web workbench no longer exists.** `WebGui` was removed from FreeCAD; only
  a headless `Mod/Web/App` remains. The current way to host HTML in the window is
  a `QWebEngineView` placed in a `QDockWidget` or the MDI area, which is what
  FreeCAD's own Help module does in 1.1.3. This panel follows that pattern.
- **QtWebEngine is optional in FreeCAD builds.** FreeCAD's Help module carries a
  fallback for exactly this case, so the panel probes the same way and opens the
  system browser instead of failing. If your build lacks it, embedding is not
  available at all — check with `CascadiaPanel.webengine_available()` before
  planning around it.

The panel uses a persistent web profile under FreeCAD's user data directory, so
the Cascadia session survives restarts. Without that, an embedded panel means
logging in on every launch, which is worse than the second window.

## What it guarantees

- **Head resolution.** A Cascadia file id names _one version_, not the lineage.
  Checkout resolves to the current head first, so work never starts from a
  superseded revision.
- **Lock discipline.** The vault lock is taken before the download and released
  if anything afterwards fails — a stranded lock needs an administrator.
- **Integrity on the way out.** Downloaded bytes are checked against Cascadia's
  own recorded `fileHash` before work is allowed to start.
- **No accidental revisions.** An unedited working copy releases the lock
  without minting a version. Pass `--require-changes` to make that an error.
- **New head reported.** Check-in returns `head_file_id`, which differs from the
  id checked out — Cascadia mints a new row per version.

## Tests

Integration tests by necessity: lock discipline and version accounting do not
exist without a real vault.

```bash
CASCADIA_API_KEY=csc_... CASCADIA_ITEM_ID=<uuid> python bridge/tests/test_roundtrip.py
```

```bash
python bridge/tests/test_fcstd_scan.py --agent-src /path/to/agent/src
python bridge/tests/test_preflight.py  --agent-src /path/to/agent/src
```

65 checks in total: 22 over the file lifecycle (upload, checkout,
double-checkout rejection, no-op check-in, edited check-in, head advance, lock
release, sidecar guard rails), 14 over the scanner against synthesised FCStd
archives, 17 over the preflight gates, and 12 over the panel's URL and route
resolution — including the negative cases, since a check that cannot fail is not
a check. The panel's Qt half needs a running FreeCAD and is exercised by hand;
what is tested here is where it points, which is where a silent 404 comes from.

```bash
python bridge/tests/test_panel.py      # no FreeCAD required
```

## Two things to know

**Cascadia needed patching, and it is documented.** FreeCAD files were rejected
by the vault's upload allowlist; that is fixed in this tree. Two further
findings are reported but untouched. See
[CASCADIA-PATCHES.md](./CASCADIA-PATCHES.md), written to be handed to the
Cascadia maintainers as-is.

**This directory's licence is undecided.** `npm run license:check` flags these
files because Cascadia's edition manifest treats everything in this tree as
AGPL-3.0-or-later by design, and no header has been added. Two ways to resolve
it, and they are not equivalent:

- Move `bridge/` to its own repository. It shares no code with Cascadia and
  talks to it over HTTP, so it stays proprietary-capable. Recommended.
- Run `npm run license:fix` to accept AGPL for it. Not reversible.
