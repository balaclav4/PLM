"""Cascadia PLM inside the FreeCAD window.

Engineers should not alt-tab between the model and the PLM. This puts Cascadia's
web UI in a dock panel beside the 3D view — or an MDI tab next to it — so the
part, its BOM and its change order are on one screen.

Why a web view rather than a native panel: Cascadia's UI is a Vite SPA that
already knows how to render items, BOMs and ECOs, and it authenticates with a
session cookie. Re-implementing any of that in Qt would mean two UIs to keep in
step. The web view is the same application, hosted in FreeCAD's window.

**QtWebEngine is optional in FreeCAD builds.** FreeCAD's own Help module carries
a fallback for exactly this ("Help rendering is done with the system browser"),
so this module detects it the same way and degrades to the system browser rather
than failing to import. Verified against the FreeCAD 1.1.3 tag, which is the
build the design agent certifies.

Shipped as part of the Cascadia addon, so FreeCAD has already put this package
on ``sys.path`` by the time anything calls it.

    from cascadia_bridge import panel
    panel.show()                       # dock panel (default)
    panel.show(as_tab=True)            # MDI tab beside the 3D view
    panel.show_part("<part-id>")       # deep-link
    panel.hide()
"""

from __future__ import annotations

import os

try:  # available inside FreeCAD only
    import FreeCAD
    import FreeCADGui
except ImportError:  # importable outside FreeCAD so the module can be linted/tested
    FreeCAD = None
    FreeCADGui = None

DOCK_OBJECT_NAME = "CascadiaPlmPanel"
PREF_PATH = "User parameter:BaseApp/Preferences/Cascadia"
DEFAULT_URL = "http://localhost:3000"

_MISSING_WEBENGINE = (
    "PySide QtWebEngineWidgets is not available in this FreeCAD build, so the "
    "Cascadia panel cannot be embedded. Opening in the system browser instead. "
    "To embed it, use a FreeCAD build compiled with QtWebEngine."
)


def _warn(message: str) -> None:
    """Report through FreeCAD's console when there is one, stderr otherwise."""
    if FreeCAD is not None:
        FreeCAD.Console.PrintWarning(message + "\n")
    else:
        import sys

        print(message, file=sys.stderr)


def _prefs():
    return FreeCAD.ParamGet(PREF_PATH)


def base_url() -> str:
    """Cascadia's address: the environment wins, then FreeCAD preferences."""
    from_env = os.environ.get("CASCADIA_URL")
    if from_env:
        return from_env.rstrip("/")
    if FreeCAD is None:
        return DEFAULT_URL
    return _prefs().GetString("BaseUrl", DEFAULT_URL).rstrip("/")


def set_base_url(url: str) -> None:
    """Persist Cascadia's address in FreeCAD preferences."""
    _prefs().SetString("BaseUrl", url.rstrip("/"))


def webengine_available() -> bool:
    """Mirror FreeCAD's own probe (``Help.get_qtwebwidgets``)."""
    try:
        from PySide import QtWebEngineWidgets  # noqa: F401
    except Exception:
        return False
    return True


def _web_classes():
    """Return ``(QWebEngineView, QWebEngineProfile, QWebEnginePage)``.

    Qt6 moved ``QWebEngineProfile`` and ``QWebEnginePage`` into
    ``QtWebEngineCore`` while the view stayed in ``QtWebEngineWidgets``; Qt5 had
    all three in the widgets module. FreeCAD's PySide shim exposes both layouts
    depending on how it was built, so try the modern split first.
    """
    from PySide import QtWebEngineWidgets

    view = QtWebEngineWidgets.QWebEngineView
    try:
        from PySide import QtWebEngineCore

        return view, QtWebEngineCore.QWebEngineProfile, QtWebEngineCore.QWebEnginePage
    except Exception:
        return (
            view,
            getattr(QtWebEngineWidgets, "QWebEngineProfile", None),
            getattr(QtWebEngineWidgets, "QWebEnginePage", None),
        )


def _profile_directory() -> str:
    """Where the embedded browser keeps cookies.

    Without a persistent profile the session cookie dies with the FreeCAD
    process and every launch starts at the login screen — the fastest way to
    make an embedded panel more annoying than a second window.
    """
    root = FreeCAD.getUserAppDataDir() if FreeCAD else os.path.expanduser("~")
    return os.path.join(root, "Cascadia", "webprofile")


def _build_view(url: str):
    from PySide import QtCore

    view_cls, profile_cls, page_cls = _web_classes()
    view = view_cls()

    if profile_cls is not None and page_cls is not None:
        directory = _profile_directory()
        os.makedirs(directory, exist_ok=True)
        profile = profile_cls("cascadia", view)
        profile.setPersistentStoragePath(directory)
        profile.setCachePath(os.path.join(directory, "cache"))
        # Keep the login across restarts.
        if hasattr(profile, "setPersistentCookiesPolicy"):
            policy = getattr(
                profile_cls, "ForcePersistentCookies", None
            ) or getattr(
                getattr(profile_cls, "PersistentCookiesPolicy", object()),
                "ForcePersistentCookies",
                None,
            )
            if policy is not None:
                profile.setPersistentCookiesPolicy(policy)
        view.setPage(page_cls(profile, view))

    view.load(QtCore.QUrl(url))
    return view


def status() -> dict:
    """Everything needed to answer "will this work here?" without a console.

    Returned as plain data so the same answer can be shown in a dialog, printed
    by the CLI, or asserted in a test.
    """
    import platform

    ready = webengine_available()
    return {
        "webengine": ready,
        "embedding": "available" if ready else "unavailable — panel opens in the system browser",
        "base_url": base_url(),
        "url_source": (
            "CASCADIA_URL environment variable"
            if os.environ.get("CASCADIA_URL")
            else ("FreeCAD preferences" if FreeCAD is not None else "built-in default")
        ),
        "profile_dir": _profile_directory() if FreeCAD is not None else "(needs FreeCAD)",
        "in_freecad": FreeCAD is not None,
        "python": platform.python_version(),
    }


def status_text() -> str:
    """The same report as human-readable lines."""
    data = status()
    return "\n".join(
        [
            f"Embedded panel:  {data['embedding']}",
            f"QtWebEngine:     {'yes' if data['webengine'] else 'no'}",
            f"Cascadia URL:    {data['base_url']}",
            f"  from:          {data['url_source']}",
            f"Web profile:     {data['profile_dir']}",
            f"Python:          {data['python']}",
        ]
    )


def _dock_area(value: int):
    from PySide import QtCore

    return {
        1: QtCore.Qt.LeftDockWidgetArea,
        4: QtCore.Qt.TopDockWidgetArea,
        8: QtCore.Qt.BottomDockWidgetArea,
    }.get(value, QtCore.Qt.RightDockWidgetArea)


def _existing_dock():
    from PySide import QtWidgets

    mw = FreeCADGui.getMainWindow()
    return mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME) if mw else None


def show(url: str | None = None, as_tab: bool = False):
    """Open Cascadia inside FreeCAD. Returns the view, or None if it fell back.

    ``as_tab`` puts it in the MDI area beside the 3D view instead of docking it.
    A dock is usually what you want — it stays visible while you model.
    """
    target = url or base_url()

    if not webengine_available():
        _warn(_MISSING_WEBENGINE)
        # The Report view is hidden by default too, so a log line can go unseen
        # and the engineer is left wondering why a browser opened.
        if FreeCADGui is not None:
            try:
                from PySide import QtWidgets

                QtWidgets.QMessageBox.warning(
                    FreeCADGui.getMainWindow(), "Cascadia PLM", _MISSING_WEBENGINE
                )
            except Exception:
                pass
        import webbrowser

        webbrowser.open(target)
        return None

    from PySide import QtWidgets

    mw = FreeCADGui.getMainWindow()
    if mw is None:
        raise RuntimeError("no FreeCAD main window — is this a GUI session?")

    existing = _existing_dock()
    if existing is not None and not as_tab:
        existing.show()
        existing.raise_()
        view = existing.widget()
        if url:
            from PySide import QtCore

            view.load(QtCore.QUrl(target))
        return view

    view = _build_view(target)
    prefs = _prefs()

    if as_tab:
        mdi = mw.findChild(QtWidgets.QMdiArea)
        window = mdi.addSubWindow(view)
        window.setWindowTitle("Cascadia PLM")
        window.show()
        mdi.setActiveSubWindow(window)
        return view

    dock = QtWidgets.QDockWidget()
    dock.setObjectName(DOCK_OBJECT_NAME)
    dock.setWindowTitle("Cascadia PLM")
    dock.setWidget(view)
    mw.addDockWidget(_dock_area(prefs.GetInt("DockArea", 2)), dock)
    dock.setFloating(prefs.GetBool("DockFloating", False))
    dock.resize(prefs.GetInt("DockWidth", 480), prefs.GetInt("DockHeight", 800))
    dock.dockLocationChanged.connect(_remember_placement)
    dock.show()
    return view


def _remember_placement(area) -> None:
    dock = _existing_dock()
    if dock is None:
        return
    prefs = _prefs()
    prefs.SetInt("DockArea", int(getattr(area, "value", area)))
    prefs.SetBool("DockFloating", dock.isFloating())
    prefs.SetInt("DockWidth", dock.width())
    prefs.SetInt("DockHeight", dock.height())


def hide() -> None:
    dock = _existing_dock()
    if dock is not None:
        dock.hide()


def toggle():
    """Menu/toolbar friendly: show if hidden, hide if visible."""
    dock = _existing_dock()
    if dock is not None and dock.isVisible():
        hide()
        return None
    return show()


# --- deep links -------------------------------------------------------------
#
# The point of embedding is that the panel follows what you are doing. These
# mirror Cascadia's SPA routes; the bridge can call them when it checks a file
# out so the PLM lands on the right record without anyone navigating.


def navigate(path: str):
    """Point the panel at a Cascadia route such as ``/parts/<id>``."""
    return show(url=f"{base_url()}/{path.lstrip('/')}")


# Cascadia's SPA routes items by type — there is no /items/<id> — so a bare
# item id has to be told what it is. Parts is the right default here: the CAD
# round-trip only ever checks out parts.
ITEM_ROUTES = {
    "Part": "parts",
    "Document": "documents",
    "ChangeOrder": "change-orders",
    "Requirement": "requirements",
    "Task": "tasks",
    "Issue": "issues",
    "TestPlan": "test-plans",
    "TestCase": "test-cases",
    "WorkInstruction": "work-instructions",
    "WorkOrder": "work-orders",
    "PhysicalPart": "physical-parts",
    "Tool": "tools",
}


def show_item(item_id: str, item_type: str = "Part"):
    """Open an item by id. ``item_type`` picks the route Cascadia renders it at."""
    segment = ITEM_ROUTES.get(item_type)
    if segment is None:
        raise ValueError(
            f"unknown item type {item_type!r}; expected one of {sorted(ITEM_ROUTES)}"
        )
    return navigate(f"/{segment}/{item_id}")


def show_part(part_id: str):
    return navigate(f"/parts/{part_id}")


def show_change_order(eco_id: str):
    return navigate(f"/change-orders/{eco_id}")


def show_working_copy(workdir) -> object:
    """Open the record a bridge working copy is bound to.

    Reads the sidecar the bridge wrote at checkout, so the panel can be pointed
    at the right part from the directory the engineer is actually working in.
    """
    import json
    from pathlib import Path

    sidecar = Path(workdir) / ".cascadia-bridge.json"
    if not sidecar.exists():
        raise FileNotFoundError(f"no .cascadia-bridge.json in {workdir}")
    binding = json.loads(sidecar.read_text())
    if binding.get("change_order_id"):
        return show_change_order(binding["change_order_id"])
    return show_item(binding["item_id"])
