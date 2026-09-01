# Cascadia PLM for FreeCAD

A FreeCAD addon that puts Cascadia's PLM interface in a dock panel beside the 3D
view, and moves FCStd files between Cascadia's file vault and a design-job
working copy without losing track of which vault version the work descends from.

Installed locally from a git clone. Nothing here talks to the FreeCAD addon
index, and nothing phones home.

## Install

If anything goes wrong, one command reports the whole picture:

```bash
python doctor.py            # read-only: FreeCAD, user dir, Mod contents, load check
```

```bash
python install.py --where   # report what was found, change nothing
python install.py           # symlink — edits take effect on restart
python install.py --copy    # copy instead
python install.py --uninstall
```

Python rather than a shell script because FreeCAD's certified platform is
Windows, where a `.sh` is useless. Start with `--where`: it prints the FreeCAD
it found, the user directory, how it worked that out, and whether the addon is
already installed — without touching anything.

> **fish shell users:** `VAR=value command` is bash syntax and does not work in
> fish. Use `env VAR=value command`, e.g.
> `env FREECAD_USER_DIR=/path python install.py`, or `set -x VAR value` first.
> The same applies to `CASCADIA_URL` and `CASCADIA_API_KEY` below.

It looks for FreeCAD's user directory in three ways, in order: the
`FREECAD_USER_DIR` environment variable, then `FreeCAD --get-config UserAppData`
if a FreeCAD is on PATH, then the standard location for your platform
(`%APPDATA%\FreeCAD`, `~/Library/Application Support/FreeCAD`,
`~/.local/share/FreeCAD`). If none of those work it says exactly what it checked
rather than guessing and installing somewhere FreeCAD will never look.

`--get-config` is a non-interactive config query. Note for anyone tempted to
script FreeCAD themselves: `-c` is **`--console`**, which starts an interactive
interpreter and will hang a script trying to read its output.

Restart FreeCAD. **A Cascadia button appears in the main toolbar** — always
visible, in every workbench — and **the panel opens by itself** — Cascadia is simply there when
FreeCAD is, docked beside the model, with no macro to run and no workbench to
find.

To reopen it after closing, or to reload the code during development:
**Macro → Macros… → CascadiaPLM → Execute**. The macro reloads the package
first, so edits to a symlinked checkout take effect without restarting FreeCAD.

The toolbar button toggles the panel and shows its pressed state, so it stays
honest when the dock is closed by its own X. It is added to the main window
rather than to a workbench: a workbench toolbar only exists while that workbench
is active, so the button would vanish the moment anyone switched to Part Design.

The **Cascadia PLM** workbench also carries two buttons, if your UI surfaces it:

- **Cascadia PLM panel** — show or hide the dock.
- **Cascadia PLM status** — whether this build can embed the panel, and where
  the panel points.

Point it at your instance by setting `CASCADIA_URL` before launching FreeCAD.
The status button shows which URL is in effect and where that value came from.

To stop it opening automatically, set `AutoShow` to false under
`BaseApp/Preferences/Cascadia` (Tools → Edit parameters). A build without
QtWebEngine is never auto-opened — launching your system browser at every
FreeCAD start would be obnoxious.

### Why an addon rather than a macro

FreeCAD loads every directory under `Mod/` at startup and puts it on `sys.path`
(`FreeCADInit.py`, `sys.path.insert(0, Dir)`). That is what makes
`import cascadia_bridge` work inside FreeCAD with no path juggling, while the
same package stays pip-installable for the coding agent and CI:

```bash
pip install -e .        # headless: bridge, scanner, preflight
```

One checkout, two audiences.

## Headless use

The bridge, scanner and preflight checks have no FreeCAD dependency and no
third-party dependencies at all — which is also why the addon needs no `pip`
step inside FreeCAD's bundled Python, where installing is often impossible.

```bash
export CASCADIA_URL=http://localhost:3000
export CASCADIA_API_KEY=csc_...        # Cascadia → Settings → API Keys

cascadia-bridge checkout <file-id> --into ./job-workspace --eco <eco-id>
cascadia-bridge status  --from ./job-workspace
cascadia-bridge checkin --from ./job-workspace --message "fillet added"
```

`checkout` writes a `.cascadia-bridge.json` sidecar recording the vault file id,
item id, version, SHA-256 at checkout, and the ECO and job ids. `checkin` reads
it back, compares digests, and mints a new version only if the bytes changed.

### What the round-trip guarantees

- **Head resolution.** A Cascadia file id names _one version_, not the lineage.
  Checkout resolves to the current head, so work never starts from a superseded
  revision.
- **Lock discipline.** The vault lock is taken before the download and released
  if anything afterwards fails — a stranded lock needs an administrator.
- **Integrity on the way out.** Downloaded bytes are checked against Cascadia's
  own recorded `fileHash` before work starts.
- **No accidental revisions.** An unedited working copy releases the lock
  without minting a version. `--require-changes` makes that an error instead.
- **New head reported.** Check-in returns `head_file_id`, which differs from the
  id checked out.

## Before building on any of this

**Will the design agent accept your models?** It refuses scripted FreeCAD
documents — `App::FeaturePython`, Python proxies, Python-object properties —
before FreeCAD opens the archive. Assembly4, the fasteners workbench and most
parametric addons persist exactly those types. This is not configurable: the
check _is_ the agent's trust boundary.

```bash
fcstd-scan /path/to/model/library --agent-src /path/to/agent/src
# Scanned 214 models — 176 accepted, 38 refused (82.2% usable)
```

The scanner imports the agent's own `fcstd_security` module and calls the same
function the agent calls, so the verdict is the real one. Without an agent
checkout it falls back to a cruder check and says so; `--require-agent` refuses
to guess. Run this first — a low acceptance rate changes the project.

**Is the environment the one the agent certified?**

```bash
cascadia-preflight freecad /path/to/FreeCADCmd --expect-sha256 <digest>
cascadia-preflight contract /path/to/agent/src --snapshot agent-tool-contract.json
```

The agent certifies FreeCAD 1.1.3 by digest and blocks anything else outright.
The contract check diffs the agent's 78 MCP tools against the recorded snapshot,
so an upstream rename fails a check instead of a design session.

To vendor the third-party FreeCAD GUI MCP at the commit the agent audited:

```bash
./scripts/vendor-freecad-mcp.sh ../freecad-mcp [your-fork-url]
```

### If the workbench does not appear

Addons that replace FreeCAD's interface — **FreeCAD-Ribbon** is the common one —
build their layout from a stored structure plus `Gui.listWorkbenches()`, so a
newly installed workbench may not surface as a tab, and the stock
`View → Workbench` menu may not exist at all. The workbench is registered
either way; you just cannot reach it by the usual route.

The macro above sidesteps this entirely. To confirm what is going on, move
`Mod/FreeCAD-Ribbon` aside and restart: the stock menus return, and
`View → Workbench → Cascadia PLM` should be listed.

## Two FreeCAD facts worth knowing

- **The Web workbench no longer exists.** `WebGui` was removed; only a headless
  `Mod/Web/App` remains in both master and the 1.1.3 tag. The current way to host
  HTML in the window is a `QWebEngineView` in a `QDockWidget` or the MDI area,
  which is what FreeCAD's own Help module does. This panel follows that pattern.
- **QtWebEngine is optional in FreeCAD builds.** FreeCAD's Help module carries a
  fallback for exactly this, so the panel probes the same way and opens the
  system browser rather than failing. If your build lacks it, embedding is not
  possible at all — the **Cascadia PLM status** button reports that directly,
  and the panel raises a dialog rather than only logging to the Report view,
  which is hidden by default too.

### Navigating

The panel carries browser chrome above the view: **back**, **forward**,
**reload**, **stop**, **home**, an **address bar**, and **open externally**
(hands the current page to your normal browser). A thin progress line shows
under the toolbar while a page loads.

Back, forward, reload and stop are bound to the web page's own actions, so Qt
manages their enabled state — back greys out with no history, stop is live only
while loading.

The address bar takes a path as readily as a URL: `/parts` goes to the current
instance, `localhost:3000/x` gets a scheme added, and a full URL is used as
typed. It stops updating while focused so it does not overwrite what you are
mid-way through typing.

The panel keeps a persistent web profile under FreeCAD's user data directory, so
the Cascadia session survives restarts. Without that, an embedded panel means
logging in on every launch — worse than a second window.

## Tests

```bash
python tests/test_install.py                            # no FreeCAD needed
python tests/test_workbench_load.py                     # no FreeCAD needed
python tests/test_panel.py                              # no FreeCAD needed
python tests/test_fcstd_scan.py --agent-src <agent/src>
python tests/test_preflight.py  --agent-src <agent/src>

CASCADIA_API_KEY=csc_... CASCADIA_ITEM_ID=<uuid> python tests/test_roundtrip.py
```

137 checks: 22 over the file lifecycle, 14 over the scanner against synthesised
FCStd archives, 17 over the preflight gates, 47 over the panel's URL, route, status, address bar and toolbar, 19 over the installer's path
resolution and macro handling, and 25 over the workbench module loading, registering, startup and icon
resolution — negative cases included, since a check that cannot fail is not a
check. The panel's Qt half needs a running FreeCAD and is exercised by hand;
what is tested here is where it points, which is where a silent 404 comes from.

## Scope

Deliberately not included:

- **The mechanical design agent.** It needs Python 3.12, psycopg, neo4j and
  pgvector, and cannot live in FreeCAD's bundled interpreter. It is already an
  external MCP server.
- **`freecad-mcp`.** A separate third-party addon, vendored at its own pinned
  commit by the script above.
- **Checkout/check-in toolbar buttons.** The coding agent drives those
  conversationally today. Adding commands later is additive — same package, same
  bridge.

## Installing through FreeCAD's Addon Manager

This repository's root is the addon, which is what lets FreeCAD install it
directly — Addon Manager clones a repository root, so it cannot install a
subdirectory of a monorepo.

1. **Tools → Addon manager**
2. The gear icon (⚙) → **Custom repositories**
3. Add:
   - **Repository URL:** `https://github.com/balaclav4/FreeCAD-Cascadia-Addon`
   - **Branch:** `main`
4. Close preferences, refresh the addon list, install **Cascadia PLM**, restart.

Requires FreeCAD 1.0 or newer. (The mechanical design agent separately certifies
exactly 1.1.3, but that is an external component — this addon does not need it.)

Updates then come from Addon Manager's own update button. `install.py` remains
for offline machines, symlinked working checkouts, and the case below.

### If Addon Manager crashes on startup

Some FreeCAD builds ship an Addon Manager with this bug:

```
addonmanager_workers_startup.py, in run
    details += f"{addon.display_name} is missing addons {', '.join(deps.external_addons)}\n"
TypeError: sequence item 0: expected str instance, Addon found
```

It joins `Addon` objects as if they were strings.

**This affects stock FreeCAD 1.1.3.** Its `src/Mod/AddonManager` submodule pins
AddonManager `937b687`, and that commit carries the broken line — at line 706,
matching the traceback exactly. The AddonManager project fixed it upstream in
`a62f301` (`', '.join([x.display_name for x in ...])`), but that fix is not in
the 1.1.3 release.

So "update FreeCAD" is not a workaround here: 1.1.3 is current, and it is also
the build the mechanical design agent certifies, so downgrading or upgrading to
dodge this trades one blocker for another.

It is not caused by this addon: that list is populated only from `<depend>`
elements in a `package.xml`, and this one declares none. It fires when any
_already installed_ addon has an unmet dependency, and it crashes the manager
before it can show you anything.

Until a FreeCAD release ships the fixed AddonManager, install with
`python install.py`. On 1.1.3 that is the install path, not a fallback.

The crash only fires when an installed addon has an unmet dependency, so
removing or repairing that addon also clears it — but Addon Manager crashes
before telling you which addon, which is what makes it awkward.

The URL and branch above are also recorded in `package.xml`; Addon Manager warns
if they disagree with where it actually fetched from, so change both together.

## Licence

Declared `UNLICENSED` in `package.xml` and no LICENSE file is present, which
means all rights reserved by default. That is a placeholder, not a decision.

This code shares nothing with Cascadia and talks to it over HTTP, so Cascadia's
AGPL does not reach it — MIT, Apache-2.0 or proprietary are all open choices.
