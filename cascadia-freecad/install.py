#!/usr/bin/env python3
"""Install this addon into FreeCAD, locally.

    python install.py --where     # just report what was found, change nothing
    python install.py             # symlink into FreeCAD's Mod directory
    python install.py --copy      # copy instead of symlinking
    python install.py --uninstall # remove it again

Works on Windows, macOS and Linux with no shell dependency, because FreeCAD's
certified platform is Windows and a .sh installer is useless there.

Finding FreeCAD's user directory, in order:

1. ``FREECAD_USER_DIR`` if you set it — always wins.
2. ``FreeCAD --get-config UserAppData``, if a FreeCAD executable is on PATH.
   This is a non-interactive config query. Do not be tempted by ``-c``: that is
   ``--console``, which starts an interactive interpreter and will hang a script
   that tries to read its output.
3. The standard per-platform locations, if one exists on disk.

If all three fail it says so and tells you how to find the path by hand, rather
than guessing and installing somewhere FreeCAD will never look.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ADDON_NAME = "CascadiaPLM"
SOURCE = Path(__file__).resolve().parent

# Only these are copied into Mod/ — tests and scratch files have no business there.
MACRO_NAME = "CascadiaPLM.FCMacro"

ADDON_CONTENTS = (
    "package.xml",
    "Init.py",
    "InitGui.py",
    "pyproject.toml",
    "README.md",
    "cascadia_bridge",
    "resources",
    "agent-tool-contract.json",
)

FREECAD_EXECUTABLES = ("FreeCAD", "freecad", "FreeCADCmd", "freecadcmd")


def candidate_user_dirs() -> list[Path]:
    """Standard FreeCAD user-data locations for this platform."""
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        roots = [Path(appdata)] if appdata else [home / "AppData" / "Roaming"]
        return [root / "FreeCAD" for root in roots]
    if system == "Darwin":
        return [home / "Library" / "Application Support" / "FreeCAD"]
    # Linux: 1.x follows XDG; older builds used a dotfile directory.
    xdg = os.environ.get("XDG_DATA_HOME")
    dirs = [Path(xdg) / "FreeCAD"] if xdg else [home / ".local" / "share" / "FreeCAD"]
    dirs.append(home / ".FreeCAD")
    return dirs


def ask_freecad(key: str = "UserAppData") -> tuple[Path | None, str | None]:
    """Query a FreeCAD on PATH for a configuration path.

    ``UserAppData`` is the user directory, ``UserMacroPath`` the macro
    directory. Returns ``(path, executable)``; ``(None, None)`` if no FreeCAD
    answered.

    The output is scanned from the end for a line that is a real directory:
    FreeCAD prints Qt and icon-theme warnings on some systems, and on at least
    one it segfaults after answering — the answer is still in there.
    """
    for name in FREECAD_EXECUTABLES:
        executable = shutil.which(name)
        if not executable:
            continue
        try:
            result = subprocess.run(
                [executable, "--get-config", key],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in reversed((result.stdout or "").splitlines()):
            candidate = Path(line.strip().strip('"'))
            if line.strip() and candidate.is_dir():
                return candidate, executable
    return None, None


def resolve_macro_dir(user_dir: Path) -> tuple[Path, str]:
    """Where FreeCAD looks for macros.

    It is configurable (Macro > Macros... shows "User macros location"), so ask
    FreeCAD rather than assume. Falls back to the standard ``Macro`` beside the
    user directory.
    """
    override = os.environ.get("FREECAD_MACRO_DIR")
    if override:
        return Path(override).expanduser(), "FREECAD_MACRO_DIR"
    path, executable = ask_freecad("UserMacroPath")
    if path is not None:
        return path, f"{executable} --get-config UserMacroPath"
    return user_dir / "Macro", "standard location beside the user directory"


def resolve_user_dir() -> tuple[Path | None, str]:
    """Find FreeCAD's user directory and say how it was found."""
    override = os.environ.get("FREECAD_USER_DIR")
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise SystemExit(f"FREECAD_USER_DIR is set to {path}, which does not exist.")
        return path, "FREECAD_USER_DIR"

    path, executable = ask_freecad()
    if path is not None:
        return path, f"{executable} --get-config UserAppData"

    for candidate in candidate_user_dirs():
        if candidate.is_dir():
            return candidate, f"standard location for {platform.system()}"

    return None, "not found"


def report(user_dir: Path | None, how: str) -> None:
    print(f"Platform:        {platform.system()}")
    print(f"Addon source:    {SOURCE}")
    freecad = next((shutil.which(n) for n in FREECAD_EXECUTABLES if shutil.which(n)), None)
    print(f"FreeCAD on PATH: {freecad or 'no'}")
    if user_dir is None:
        print("User directory:  NOT FOUND")
        print("\nChecked:")
        for candidate in candidate_user_dirs():
            print(f"  {candidate}  {'(exists)' if candidate.is_dir() else '(missing)'}")
        print(
            "\nFind it from FreeCAD itself — Help > About FreeCAD lists the user\n"
            "config path, or run FreeCAD once so the directory gets created — then:\n"
            "  FREECAD_USER_DIR=/that/path python install.py"
        )
        return
    print(f"User directory:  {user_dir}")
    print(f"  found via:     {how}")
    target = user_dir / "Mod" / ADDON_NAME
    if target.is_symlink():
        print(f"Installed:       yes (symlink -> {target.resolve()})")
    elif target.exists():
        print(f"Installed:       yes (copy at {target})")
    else:
        print(f"Installed:       no (would install to {target})")


def install(user_dir: Path, copy: bool) -> Path:
    target = user_dir / "Mod" / ADDON_NAME
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.is_symlink() or target.exists():
        print(f"Replacing existing install at {target}")
        uninstall(user_dir, quiet=True)

    if copy:
        target.mkdir(parents=True)
        for entry in ADDON_CONTENTS:
            source = SOURCE / entry
            if not source.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, target / entry, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, target / entry)
        print(f"Copied the addon to {target}")
    else:
        try:
            target.symlink_to(SOURCE, target_is_directory=True)
            print(f"Symlinked {target} -> {SOURCE}")
            print("Edits in this checkout take effect when FreeCAD restarts.")
        except OSError as error:
            # Windows needs Developer Mode or admin rights for symlinks.
            print(f"Symlink failed ({error}); copying instead.")
            return install(user_dir, copy=True)
    return target


def install_macro(user_dir: Path) -> Path | None:
    """Copy the launcher macro into FreeCAD's Macro directory.

    A workbench is only reachable through whatever UI is running, and a replaced
    interface (FreeCAD-Ribbon, for instance) builds its layout from its own
    stored structure, so a newly installed workbench may not appear as a tab.
    Macros are reachable in every FreeCAD UI, which makes this the reliable way
    in.
    """
    source = SOURCE / MACRO_NAME
    if not source.exists():
        return None
    macro_dir, _ = resolve_macro_dir(user_dir)
    macro_dir.mkdir(parents=True, exist_ok=True)
    target = macro_dir / MACRO_NAME
    shutil.copy2(source, target)
    return target


def uninstall(user_dir: Path, quiet: bool = False) -> None:
    target = user_dir / "Mod" / ADDON_NAME
    removed = False
    if target.is_symlink():
        target.unlink()
        removed = True
    elif target.is_dir():
        shutil.rmtree(target)
        removed = True

    macro_dir, _ = resolve_macro_dir(user_dir)
    macro = macro_dir / MACRO_NAME
    if macro.exists():
        macro.unlink()
        removed = True

    if not quiet:
        print(f"Removed {target}" if removed else f"Nothing installed at {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--where", action="store_true", help="report what was found, change nothing")
    parser.add_argument("--copy", action="store_true", help="copy instead of symlinking")
    parser.add_argument("--uninstall", action="store_true", help="remove the addon")
    args = parser.parse_args(argv)

    user_dir, how = resolve_user_dir()

    if args.where:
        report(user_dir, how)
        return 0 if user_dir else 1

    if user_dir is None:
        report(None, how)
        return 1

    if args.uninstall:
        uninstall(user_dir)
        return 0

    print(f"FreeCAD user directory: {user_dir}  (via {how})")
    install(user_dir, copy=args.copy)
    macro = install_macro(user_dir)
    if macro:
        _, macro_how = resolve_macro_dir(user_dir)
        print(f"Installed launcher macro: {macro}")
        print(f"  macro directory found via: {macro_how}")

    print(
        "\nInstalled. Next:\n"
        "  1. Restart FreeCAD.\n"
        "  2. Macro > Macros... > CascadiaPLM > Execute\n"
        "     (works in any FreeCAD UI, including replaced ones like Ribbon)\n"
        "     or, in the stock UI, View > Workbench > Cascadia PLM.\n"
        "  3. The macro prints a status report first — whether this build can dock\n"
        "     the panel, and where the panel points.\n\n"
        "Set CASCADIA_URL before launching FreeCAD to point it at your instance."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
