"""Does InitGui.py actually load, and register what it claims?

FreeCAD executes ``InitGui.py`` for every directory under ``Mod/`` at GUI
startup. If it raises, FreeCAD logs the traceback to the Report view and moves
on — the workbench simply never appears, with no dialog and nothing obviously
wrong. That failure is indistinguishable from "the addon is not installed",
which makes it worth testing directly.

FreeCAD is stubbed here, so this proves the module imports, registers a
workbench and two commands, and that the command bodies reach the panel. It
cannot prove Qt behaves — that still needs a real FreeCAD.

    python tests/test_workbench_load.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f" {detail}" if not condition else ""))


class _Console:
    def __init__(self):
        self.messages: list[str] = []

    def PrintLog(self, text):
        self.messages.append(text)

    PrintMessage = PrintLog
    PrintWarning = PrintLog
    PrintError = PrintLog


class _Params:
    def __init__(self):
        self.values: dict = {}

    def GetString(self, key, default=""):
        return self.values.get(key, default)

    def SetString(self, key, value):
        self.values[key] = value

    def GetInt(self, key, default=0):
        return self.values.get(key, default)

    def SetInt(self, key, value):
        self.values[key] = value

    def GetBool(self, key, default=False):
        return self.values.get(key, default)

    def SetBool(self, key, value):
        self.values[key] = value


def install_freecad_stubs() -> tuple[types.ModuleType, types.ModuleType, dict]:
    """Minimal stand-ins for the two modules FreeCAD injects."""
    registry: dict = {"workbenches": [], "commands": {}}

    freecad = types.ModuleType("FreeCAD")
    freecad.Console = _Console()
    freecad.ParamGet = lambda path: _Params()
    freecad.getUserAppDataDir = lambda: "/tmp/freecad-user"

    gui = types.ModuleType("FreeCADGui")

    class Workbench:
        """Stands in for Gui::PythonWorkbench's Python base."""

        def appendToolbar(self, name, commands):
            registry.setdefault("toolbars", []).append((name, list(commands)))

        def appendMenu(self, name, commands):
            registry.setdefault("menus", []).append((name, list(commands)))

    gui.Workbench = Workbench
    gui.addWorkbench = lambda wb: registry["workbenches"].append(wb)
    gui.addCommand = lambda name, cmd: registry["commands"].__setitem__(name, cmd)
    gui.getMainWindow = lambda: None

    sys.modules["FreeCAD"] = freecad
    sys.modules["FreeCADGui"] = gui
    return freecad, gui, registry


def main() -> int:
    freecad, gui, registry = install_freecad_stubs()

    print("\nInitGui.py loads")
    namespace: dict = {"__name__": "InitGui", "__file__": str(ROOT / "InitGui.py")}
    try:
        exec(compile((ROOT / "InitGui.py").read_text(), "InitGui.py", "exec"), namespace)
        check("InitGui.py executes without raising", True)
    except Exception as error:  # noqa: BLE001 - the point is to report any failure
        check("InitGui.py executes without raising", False, f"{type(error).__name__}: {error}")
        print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
        return 1

    print("\nregistration")
    check("a workbench was registered", len(registry["workbenches"]) == 1, str(registry["workbenches"]))
    registered = registry["workbenches"][0]
    # FreeCAD accepts a class or an instance; a known-good addon on the target
    # machine registers an instance, so match that.
    check("an instance was registered, not the class", not isinstance(registered, type))
    workbench = type(registered)
    check("it is the Cascadia workbench", workbench.__name__ == "CascadiaWorkbench")
    check(
        "the name matches package.xml's classname",
        "CascadiaWorkbench" in (ROOT / "package.xml").read_text(),
    )
    check("MenuText is set", bool(getattr(workbench, "MenuText", "")))

    print("\nInitialize() wires the toolbar")
    registered.Initialize()
    check("both commands registered", set(registry["commands"]) == {"Cascadia_Panel", "Cascadia_Status"}, str(set(registry["commands"])))
    check("a toolbar was appended", bool(registry.get("toolbars")), str(registry.get("toolbars")))
    check("a menu was appended", bool(registry.get("menus")))

    print("\ncommands are well-formed")
    for name, command in registry["commands"].items():
        resources = command.GetResources()
        check(f"{name} declares MenuText", bool(resources.get("MenuText")))
        check(f"{name} declares a Pixmap", bool(resources.get("Pixmap")))
        check(f"{name} is active without a document", command.IsActive() is True)

    print("\nstartup behaviour")
    check(
        "the addon directory is put on sys.path",
        str(ROOT) in sys.path,
    )
    check(
        "auto-show is scheduled on a timer, not run inline",
        "singleShot" in (ROOT / "InitGui.py").read_text(),
    )
    check(
        "auto-show can be turned off by preference",
        'GetBool("AutoShow"' in (ROOT / "InitGui.py").read_text(),
    )
    check(
        "a build without QtWebEngine is not auto-opened",
        "webengine_available" in (ROOT / "InitGui.py").read_text(),
    )

    print("\nInit.py loads too")
    try:
        exec(compile((ROOT / "Init.py").read_text(), "Init.py", "exec"), {"__name__": "Init"})
        check("Init.py executes without raising", True)
    except Exception as error:  # noqa: BLE001
        check("Init.py executes without raising", False, f"{type(error).__name__}: {error}")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
