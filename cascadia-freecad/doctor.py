#!/usr/bin/env python3
"""One command that reports everything needed to diagnose an install.

    python doctor.py

Prints FreeCAD's location and version, every user directory it checked, what is
actually in FreeCAD's Mod folder, whether this addon is installed and intact,
and whether the workbench module loads. Read-only — it changes nothing.

Written because remote-diagnosing a GUI over chat does not work: one paste of
this output answers what a dozen "do you see X?" questions cannot.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import install  # noqa: E402


def rule(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


def run(cmd: list[str], timeout: int = 60) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return ((result.stdout or "") + (result.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return f"<failed: {error}>"


def main() -> int:
    print("Cascadia PLM addon — install doctor")

    rule("this machine")
    print(f"Platform:  {platform.system()} {platform.release()}")
    print(f"Python:    {sys.version.split()[0]}  ({sys.executable})")
    print(f"Addon src: {ROOT}")

    rule("which build is this")
    build = None
    try:
        sys.path.insert(0, str(ROOT))
        from cascadia_bridge import panel

        build = panel.build_info()
        print(f"commit:    {build['commit']} on {build['branch']}")
        if build["dirty"]:
            print("           (uncommitted edits in this checkout)")
        print(f"source:    {build['path']}")
    except Exception as error:
        print(f"could not read build info: {error}")

    fetch = run(["git", "-C", str(ROOT), "fetch", "--quiet"], timeout=120)
    counts = run(["git", "-C", str(ROOT), "rev-list", "--left-right", "--count", "@{upstream}...HEAD"])
    if counts and "\t" in counts:
        behind, ahead = counts.split("\t")[:2]
        behind, ahead = behind.strip(), ahead.strip()
        if behind != "0":
            print(f"\nBEHIND the remote by {behind} commit(s) — run:  git pull")
        elif ahead != "0":
            print(f"up to date (and {ahead} local commit(s) ahead)")
        else:
            print("up to date with the remote")
    elif fetch:
        print(f"could not compare with the remote: {fetch.splitlines()[0][:80]}")

    rule("freecad")
    found = []
    for name in install.FREECAD_EXECUTABLES:
        path = shutil.which(name)
        if path:
            found.append((name, path))
            print(f"on PATH:   {name} -> {path}")
    if not found:
        print("on PATH:   none of " + ", ".join(install.FREECAD_EXECUTABLES))
        print("           (normal on Windows/macOS — not itself a problem)")
    else:
        version = run([found[0][1], "--version"])
        print(f"version:   {version.splitlines()[0] if version else '<no output>'}")
        print(f"UserAppData: {run([found[0][1], '--get-config', 'UserAppData']) or '<no output>'}")

    rule("user directory")
    override = os.environ.get("FREECAD_USER_DIR")
    print(f"FREECAD_USER_DIR: {override or '<unset>'}")
    for candidate in install.candidate_user_dirs():
        print(f"  checked: {candidate}  {'EXISTS' if candidate.is_dir() else 'missing'}")

    try:
        user_dir, how = install.resolve_user_dir()
    except SystemExit as error:
        print(f"\nresolution failed: {error}")
        user_dir, how = None, "failed"

    if user_dir is None:
        print("\nRESULT: FreeCAD's user directory was not found.")
        print("If FreeCAD has never been launched on this machine, that directory")
        print("does not exist yet — start FreeCAD once, close it, and re-run.")
        print("Otherwise find the path via Edit > Preferences > General, then:")
        print("  FREECAD_USER_DIR=<that path> python install.py")
        return 1

    print(f"\nresolved: {user_dir}   (via {how})")

    rule("macro directory")
    macro_dir, macro_how = install.resolve_macro_dir(user_dir)
    print(f"macros: {macro_dir}")
    print(f"  found via: {macro_how}")
    macro = macro_dir / install.MACRO_NAME
    print(f"  {install.MACRO_NAME}: {'present' if macro.exists() else 'NOT PRESENT'}")
    if not macro.exists():
        print("  (run  python install.py  to place it)")
    print("  In FreeCAD, Macro > Macros... shows the location it actually reads;")
    print("  if it differs from the above, point it here or re-run with")
    print("  FREECAD_MACRO_DIR set to that path.")

    rule("what freecad would load")
    mod = user_dir / "Mod"
    if not mod.is_dir():
        print(f"{mod} does not exist — nothing is installed for this user.")
    else:
        entries = sorted(p.name for p in mod.iterdir())
        print(f"{mod} contains {len(entries)} item(s):")
        for name in entries:
            marker = "  <-- this addon" if name == install.ADDON_NAME else ""
            print(f"  {name}{marker}")

    rule("this addon")
    target = mod / install.ADDON_NAME
    if not target.exists():
        print(f"NOT INSTALLED at {target}")
        print("\nRESULT: run  python install.py  then restart FreeCAD.")
        return 1

    print(f"installed at: {target}")
    if target.is_symlink():
        print(f"  symlink -> {target.resolve()}")
    missing = [f for f in ("package.xml", "Init.py", "InitGui.py", "cascadia_bridge") if not (target / f).exists()]
    if missing:
        print(f"  INCOMPLETE — missing: {', '.join(missing)}")
        print("\nRESULT: reinstall with  python install.py --copy")
        return 1
    print("  contents look complete")

    rule("does the workbench load")
    probe = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "test_workbench_load.py")],
        capture_output=True,
        text=True,
    )
    last = [line for line in probe.stdout.splitlines() if line.strip()]
    print(last[-1] if last else "<no output>")
    if probe.returncode != 0:
        print("The workbench module fails to load — that is a code bug, not an install one.")
        print(probe.stdout[-800:])
        return 1

    rule("verdict")
    print("The addon is installed and its workbench module loads.")
    print("\nIn FreeCAD, either:")
    print("  Macro > Macros... > CascadiaPLM > Execute      (works in any UI)")
    print("  View > Workbench > Cascadia PLM                (stock UI only)")

    replacements = [n for n in ("FreeCAD-Ribbon", "Ribbon") if (mod / n).exists()]
    if replacements:
        print(f"\nNOTE: {', '.join(replacements)} is installed. Addons that replace")
        print("FreeCAD's interface build their layout from their own stored structure,")
        print("so this workbench may not appear as a tab and View > Workbench may not")
        print("exist. Use the macro. To check, move the replacement aside and restart.")

    print("\nIf neither route works:")
    print("  1. FreeCAD must be restarted after installing or pulling — InitGui.py")
    print("     runs only at startup, and Python caches imported modules, so a")
    print("     running FreeCAD keeps using the code it loaded.")
    print("  2. Check the Report view for a line starting 'Cascadia PLM:'.")
    print("  3. Compare the commit above with what the status button reports")
    print("     inside FreeCAD. If they differ, FreeCAD is running older code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
