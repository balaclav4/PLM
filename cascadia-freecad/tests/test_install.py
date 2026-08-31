"""Tests for the installer's path resolution.

This is the code that failed first contact: the original shell installer asked
FreeCAD for its user directory with ``-c``, which is ``--console`` and starts an
interactive interpreter, so it hung or errored instead of answering. These
checks cover the resolution order and the install/uninstall round trip, since
that is where a wrong answer sends the addon somewhere FreeCAD never looks.

    python tests/test_install.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import install  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f" {detail}" if not condition else ""))


def main() -> int:
    print("\nplatform candidates")
    candidates = install.candidate_user_dirs()
    check("at least one candidate for this platform", len(candidates) >= 1)
    check("candidates are absolute", all(c.is_absolute() for c in candidates))
    check("candidates name FreeCAD", all("FreeCAD" in str(c) for c in candidates))

    print("\nresolution order")
    saved = os.environ.get("FREECAD_USER_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["FREECAD_USER_DIR"] = str(root)
        resolved, how = install.resolve_user_dir()
        check("an explicit override wins", resolved == root, f"got {resolved}")
        check("the source of the answer is reported", how == "FREECAD_USER_DIR", how)

        os.environ["FREECAD_USER_DIR"] = str(root / "does-not-exist")
        try:
            install.resolve_user_dir()
            check("a bad override is rejected", False, "it was accepted")
        except SystemExit:
            check("a bad override is rejected", True)

        os.environ["FREECAD_USER_DIR"] = str(root)

        print("\ninstall round trip")
        target = install.install(root, copy=True)
        check("installs under Mod/", target == root / "Mod" / install.ADDON_NAME)
        check("the addon manifest is present", (target / "package.xml").exists())
        check("the workbench entry point is present", (target / "InitGui.py").exists())
        check("the package came along", (target / "cascadia_bridge" / "panel.py").exists())
        check("tests are excluded from Mod/", not (target / "tests").exists())
        check(
            "no __pycache__ is copied",
            not list(target.rglob("__pycache__")),
        )

        print("\nlauncher macro")
        macro = install.install_macro(root)
        check("the macro is installed", macro is not None and macro.exists(), str(macro))
        check("it lands in Macro/", macro.parent == root / "Macro")
        check("it references the panel", "cascadia_bridge" in macro.read_text())

        print("\nwhat FreeCAD would import")
        sys.path.insert(0, str(target))
        for module in ("cascadia_bridge", "cascadia_bridge.panel"):
            sys.modules.pop(module, None)
        import cascadia_bridge  # noqa: F401

        check("the installed tree imports", True)

        print("\nreinstall and uninstall")
        install.install(root, copy=True)
        check("reinstall over an existing copy works", (target / "package.xml").exists())
        install.uninstall(root)
        check("uninstall removes it", not target.exists())
        check("uninstall removes the macro too", not (root / "Macro" / install.MACRO_NAME).exists())

    if saved is None:
        os.environ.pop("FREECAD_USER_DIR", None)
    else:
        os.environ["FREECAD_USER_DIR"] = saved

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
