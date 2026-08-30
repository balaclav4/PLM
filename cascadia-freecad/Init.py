"""Non-GUI startup for the Cascadia addon.

FreeCAD executes this for every directory under ``Mod/`` at launch, GUI or not,
and puts that directory on ``sys.path`` first — which is the whole reason this
integration is packaged as an addon rather than a loose macro. ``import
cascadia_bridge`` then works inside FreeCAD with no path juggling, and the same
package stays pip-installable for the coding agent and for CI.

Nothing is imported here on purpose. Startup cost belongs to the command that
opens the panel, not to every FreeCAD launch.
"""
