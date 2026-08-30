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


class CascadiaWorkbench(FreeCADGui.Workbench):
    MenuText = "Cascadia PLM"
    ToolTip = "Product lifecycle management beside the model"
    Icon = "ApplicationsWeb"

    def Initialize(self):
        FreeCADGui.addCommand("Cascadia_Panel", CascadiaPanelCommand())
        commands = ["Cascadia_Panel"]
        self.appendToolbar("Cascadia PLM", commands)
        self.appendMenu("Cascadia PLM", commands)

    def Activated(self):
        FreeCAD.Console.PrintLog("Cascadia PLM workbench activated\n")

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CascadiaWorkbench)
