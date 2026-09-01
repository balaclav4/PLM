"""Workbench registration and startup.

Follows the conventions of ForgeTerm, which is a working addon on the same
machine: the addon directory is put on ``sys.path`` explicitly rather than
trusting FreeCAD to have done it, and the workbench is registered as an
*instance*.

The panel is opened at startup by default, so Cascadia is simply there when
FreeCAD is — no macro to run, no workbench to find. Set ``AutoShow`` to false
under ``BaseApp/Preferences/Cascadia`` to make it manual instead.
"""

import os as _os
import sys as _sys

try:
    _addon_dir = _os.path.dirname(_os.path.abspath(__file__))
except NameError:  # executed without __file__ in some hosts
    import inspect as _inspect

    _addon_dir = _os.path.dirname(_os.path.abspath(_inspect.getfile(_inspect.currentframe())))

# FreeCAD normally does this for every Mod/ directory, but doing it here as well
# means the addon still imports if it was loaded some other way.
if _addon_dir not in _sys.path:
    _sys.path.insert(0, _addon_dir)

import FreeCAD
import FreeCADGui

PREF_PATH = "User parameter:BaseApp/Preferences/Cascadia"
STARTUP_DELAY_MS = 2500


class CascadiaPanelCommand:
    """Show or hide the docked Cascadia panel."""

    def GetResources(self):
        from cascadia_bridge import panel

        return {
            "Pixmap": panel.icon_path(),
            "MenuText": "Cascadia PLM panel",
            "ToolTip": "Show or hide Cascadia PLM beside the model",
        }

    def Activated(self):
        from cascadia_bridge import panel

        panel.toggle()

    def IsActive(self):
        return True


class CascadiaStatusCommand:
    """Report whether this build can host the panel, and where it points.

    A button because the Python console and the Report view are both hidden by
    default; asking someone to open one to find out whether the addon works is a
    bad first experience.
    """

    def GetResources(self):
        return {
            "Pixmap": "Std_DlgParameter",
            "MenuText": "Cascadia PLM status",
            "ToolTip": "Check whether this FreeCAD build can embed the panel",
        }

    def Activated(self):
        from PySide import QtWidgets

        from cascadia_bridge import panel

        report = panel.status_text()
        FreeCAD.Console.PrintMessage("Cascadia PLM status\n" + report + "\n")

        box = QtWidgets.QMessageBox(FreeCADGui.getMainWindow())
        box.setWindowTitle("Cascadia PLM status")
        box.setIcon(
            QtWidgets.QMessageBox.Information
            if panel.webengine_available()
            else QtWidgets.QMessageBox.Warning
        )
        box.setText(
            "The panel can dock inside FreeCAD."
            if panel.webengine_available()
            else "This FreeCAD build cannot embed the panel.\n"
            "It will open in your system browser instead."
        )
        box.setDetailedText(report)
        box.exec()

    def IsActive(self):
        return True


FreeCADGui.addCommand("Cascadia_Panel", CascadiaPanelCommand())
FreeCADGui.addCommand("Cascadia_Status", CascadiaStatusCommand())


class CascadiaWorkbench(FreeCADGui.Workbench):
    MenuText = "Cascadia PLM"
    ToolTip = "Product lifecycle management beside the model"
    Icon = _os.path.join(_addon_dir, "resources", "cascadia.svg")

    def Initialize(self):
        commands = ["Cascadia_Panel", "Cascadia_Status"]
        self.appendToolbar("Cascadia PLM", commands)
        self.appendMenu("Cascadia PLM", commands)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def ContextMenu(self, recipient):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


# An instance, not the class: this is the form a known-good addon on this
# machine uses, and FreeCAD is happier with it.
FreeCADGui.addWorkbench(CascadiaWorkbench())


def _on_startup():
    """Put the button up, and open the panel unless told not to.

    Run from a timer rather than inline: InitGui.py executes while the GUI is
    still being assembled, and adding to a half-built main window is how a
    toolbar or dock ends up in the wrong place or nowhere.
    """
    try:
        from cascadia_bridge import panel
    except Exception as error:
        FreeCAD.Console.PrintWarning(f"Cascadia PLM: could not load the panel ({error})\n")
        return

    # The button goes up whatever else happens — it is the way back in when the
    # panel is closed, and it is wanted even on builds that cannot embed.
    try:
        panel.install_toolbar_button()
    except Exception as error:
        FreeCAD.Console.PrintWarning(f"Cascadia PLM: could not add the toolbar ({error})\n")

    if not FreeCAD.ParamGet(PREF_PATH).GetBool("AutoShow", True):
        return

    if not panel.webengine_available():
        # Auto-opening the system browser at every FreeCAD launch would be
        # obnoxious. Leave that to the button.
        FreeCAD.Console.PrintWarning(
            "Cascadia PLM: this build has no QtWebEngine, so the panel is not "
            "opened automatically. Use the toolbar button.\n"
        )
        return

    try:
        panel.show()
    except Exception as error:  # never let startup decoration break startup
        FreeCAD.Console.PrintWarning(f"Cascadia PLM: could not open the panel ({error})\n")


def _schedule_startup():
    try:
        from PySide import QtCore

        QtCore.QTimer.singleShot(STARTUP_DELAY_MS, _on_startup)
    except Exception as error:
        FreeCAD.Console.PrintWarning(f"Cascadia PLM: could not schedule startup ({error})\n")


_schedule_startup()
