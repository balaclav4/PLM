"""Workbench registration — deliberately thin.

One command: show or hide the Cascadia panel. The panel is a QDockWidget, so it
stays put when the engineer switches back to Part Design; the workbench exists
to give that command somewhere to live, not to become a second UI for the PLM.

Checkout and check-in stay with the coding agent, which already drives them
conversationally. Adding toolbar buttons for those later is additive — same
package, same bridge, a few more commands.
"""

import FreeCAD
import FreeCADGui


class CascadiaPanelCommand:
    """Toggle the docked Cascadia PLM panel."""

    def GetResources(self):
        return {
            "Pixmap": "ApplicationsWeb",
            "MenuText": "Cascadia PLM panel",
            "ToolTip": "Show or hide Cascadia PLM beside the model",
        }

    def Activated(self):
        from cascadia_bridge import panel

        panel.toggle()

    def IsActive(self):
        # Always available: the panel does not depend on an open document.
        return True


class CascadiaStatusCommand:
    """Report whether this FreeCAD build can host the panel, and where it points.

    Exists as a button because the Python console and the Report view are both
    hidden by default — asking someone to open one just to find out whether the
    addon works is a bad first experience.
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


class CascadiaWorkbench(FreeCADGui.Workbench):
    MenuText = "Cascadia PLM"
    ToolTip = "Product lifecycle management beside the model"
    Icon = "ApplicationsWeb"

    def Initialize(self):
        FreeCADGui.addCommand("Cascadia_Panel", CascadiaPanelCommand())
        FreeCADGui.addCommand("Cascadia_Status", CascadiaStatusCommand())
        commands = ["Cascadia_Panel", "Cascadia_Status"]
        self.appendToolbar("Cascadia PLM", commands)
        self.appendMenu("Cascadia PLM", commands)

    def Activated(self):
        FreeCAD.Console.PrintLog("Cascadia PLM workbench activated\n")

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CascadiaWorkbench)
