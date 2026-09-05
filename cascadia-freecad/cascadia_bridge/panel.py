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
TOOLBAR_OBJECT_NAME = "CascadiaPlmToolBar"
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


def reachable(url: str, timeout: float = 2.0) -> bool:
    """Is something answering at ``url``?

    Any HTTP response counts, including 401 or 404: the question is whether a
    server is there, not whether that particular path exists.
    """
    import urllib.error
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(urllib.request.Request(url, method="GET"), timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def startup_command() -> str:
    """The command that brings a local Cascadia up, with a real path in it.

    The path is resolved from this file rather than written out, because the
    addon is as often run from a checkout as from FreeCAD's Mod directory, and a
    command that has to be adapted before it works is one more thing to get
    wrong.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return f"python {os.path.join(root, 'scripts', 'cascadia-up.py')} --start"


def _unreachable_html(url: str) -> str:
    """Explain an unreachable Cascadia, rather than showing a browser error.

    The panel is only a window onto Cascadia; it does not start one. Landing on
    Chromium's default error page makes that look like a broken addon instead of
    a server that is not running.
    """
    return f"""<!doctype html>
<meta charset="utf-8">
<style>
  body {{ font: 15px/1.6 system-ui, sans-serif; margin: 0; padding: 32px;
         color: #1a1d1c; background: #f4f4f1; }}
  h1 {{ font-size: 19px; margin: 0 0 4px; }}
  p {{ max-width: 52ch; color: #4a5250; }}
  code {{ background: #e4e5df; padding: 1px 5px; border-radius: 3px;
          font: 13px ui-monospace, monospace; }}
  pre {{ background: #fff; border: 1px solid #d5d6d0; padding: 12px;
         overflow-x: auto; font: 12.5px ui-monospace, monospace; }}
  .url {{ font: 13px ui-monospace, monospace; color: #0e6a60; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e6e7e3; background: #171a19; }}
    p {{ color: #99a19e; }}
    code {{ background: #262b2a; }}
    pre {{ background: #1c201f; border-color: #2f3533; }}
    .url {{ color: #47bcac; }}
  }}
</style>
<h1>No Cascadia at this address</h1>
<p class="url">{url}</p>
<p>Nothing answered there. This panel is a window onto a Cascadia instance &mdash;
it does not start one, so a Cascadia server has to be running and reachable from
this machine.</p>
<p>To run one locally:</p>
<pre>{startup_command()}</pre>
<p>That checks what is missing, fixes what it safely can &mdash; the
<code>.env</code>, the database, the schema, the seed &mdash; and starts the dev
server. It finds your checkout itself, so it does not matter which directory you
run it from. Installing PostgreSQL needs root, so it prints that step rather
than running it.</p>
<p>Wait for both <code>Local: http://localhost:3000/</code> and <code>Hono API
server running on http://localhost:3001</code>, then press <b>Reload</b> above.
Sign in with <code>admin@cascadia.local</code> / <code>Cascadia</code>.</p>
<p>If Cascadia is running elsewhere, set <code>CASCADIA_URL</code> before
launching FreeCAD, or call
<code>panel.set_base_url("http://host:3000")</code>.</p>
"""


def normalize_typed_url(text: str, base: str | None = None) -> str:
    """Turn what someone types in the address bar into a URL worth loading.

    A path goes to the current instance, a bare host gets a scheme, and an
    already-complete URL is left alone. Without this, typing ``/parts`` loads
    ``file:///parts`` and typing ``localhost:3000`` is read as the ``localhost``
    scheme.
    """
    text = text.strip()
    if not text:
        return base or base_url()
    root = (base or base_url()).rstrip("/")
    if text.startswith("/"):
        return root + text
    if "://" in text:
        return text
    # host:port or host/path — a scheme is missing, not a relative path.
    head = text.split("/", 1)[0]
    if "." in head or ":" in head or head in ("localhost",):
        return "http://" + text
    return f"{root}/{text}"


def _web_action(page_cls, name: str):
    """``QWebEnginePage.WebAction.<name>``, across Qt5 and Qt6 enum layouts.

    Qt6 scopes enums under ``WebAction``; Qt5 exposed them on the class.
    """
    holder = getattr(page_cls, "WebAction", page_cls)
    return getattr(holder, name)


def _icon(widget, theme_name: str, standard_name: str):
    """A themed icon, falling back to Qt's built-in style icons.

    Icon themes are frequently missing or misconfigured — one machine here logs
    six missing themes at startup — so never depend on ``fromTheme`` alone.
    """
    from PySide import QtGui, QtWidgets

    icon = QtGui.QIcon.fromTheme(theme_name)
    if not icon.isNull():
        return icon
    holder = getattr(QtWidgets.QStyle, "StandardPixmap", QtWidgets.QStyle)
    pixmap = getattr(holder, standard_name, None)
    if pixmap is None:
        return QtGui.QIcon()
    return widget.style().standardIcon(pixmap)


def _view_of(widget):
    """The web view inside a panel container, or the widget itself."""
    return getattr(widget, "web_view", widget)


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

    if reachable(url):
        view.load(QtCore.QUrl(url))
    else:
        # setHtml needs a base URL for relative resolution; the target serves.
        view.setHtml(_unreachable_html(url), QtCore.QUrl(url))

    try:
        return _wrap_with_toolbar(view, page_cls)
    except Exception as error:
        # Chrome is a convenience; losing it must not cost the panel itself.
        _warn(f"Cascadia PLM: navigation toolbar unavailable ({error})")
        return view


def _wrap_with_toolbar(view, page_cls):
    """Put browser chrome above the view: back, forward, reload, home, address.

    A web view on its own has no navigation at all — no back button, no way to
    see or type an address, no reload. Cascadia is a multi-page application, so
    without these the panel is a one-way trip into whatever page loaded first.

    Back/forward/reload/stop are bound to the page's own ``WebAction``s rather
    than to ``view.back()`` and friends, so Qt manages their enabled state: back
    greys out with no history, stop only while loading.
    """
    from PySide import QtCore, QtWidgets

    if page_cls is None:
        # No custom page was installed, so ask the live one for its class.
        page_cls = type(view.page())

    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    bar = QtWidgets.QToolBar(container)
    bar.setIconSize(QtCore.QSize(16, 16))
    bar.setMovable(False)

    def add(theme, standard, action_name, tip):
        action = view.pageAction(_web_action(page_cls, action_name))
        action.setIcon(_icon(container, theme, standard))
        action.setToolTip(tip)
        bar.addAction(action)
        return action

    add("go-previous", "SP_ArrowBack", "Back", "Back")
    add("go-next", "SP_ArrowForward", "Forward", "Forward")
    add("view-refresh", "SP_BrowserReload", "Reload", "Reload")
    add("process-stop", "SP_BrowserStop", "Stop", "Stop loading")

    home = bar.addAction(_icon(container, "go-home", "SP_DirHomeIcon"), "Home")
    home.setToolTip("Back to the Cascadia home page")
    home.triggered.connect(lambda: view.load(QtCore.QUrl(base_url())))

    address = QtWidgets.QLineEdit(container)
    address.setPlaceholderText("Address, or a path such as /parts")
    address.setClearButtonEnabled(True)
    bar.addWidget(address)

    external = bar.addAction(
        _icon(container, "window-new", "SP_DesktopIcon"), "Open externally"
    )
    external.setToolTip("Open the current page in your normal browser")

    def go():
        view.load(QtCore.QUrl(normalize_typed_url(address.text())))
        view.setFocus()

    def show_url(qurl):
        # Do not fight the user mid-edit: only refresh when unfocused.
        if not address.hasFocus():
            address.setText(qurl.toString())

    def open_external():
        import webbrowser

        webbrowser.open(view.url().toString() or base_url())

    address.returnPressed.connect(go)
    external.triggered.connect(open_external)
    view.urlChanged.connect(show_url)

    progress = QtWidgets.QProgressBar(container)
    progress.setMaximumHeight(2)
    progress.setTextVisible(False)
    progress.setRange(0, 100)
    progress.hide()

    def on_progress(value):
        progress.setValue(value)
        progress.setVisible(0 < value < 100)

    view.loadProgress.connect(on_progress)
    view.loadFinished.connect(lambda ok: progress.hide())

    layout.addWidget(bar)
    layout.addWidget(progress)
    layout.addWidget(view, 1)

    show_url(view.url())
    container.web_view = view
    container.address_bar = address
    return container


def build_info() -> dict:
    """Which copy of this addon is actually running.

    "I pulled but nothing changed" has several causes that look identical from
    the outside — pulled in the wrong directory, FreeCAD not restarted, a copy
    install shadowing the checkout you edited. Reporting the commit the loaded
    code came from distinguishes them in one line.
    """
    import subprocess

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    info = {"path": root, "commit": "unknown", "dirty": None, "branch": "unknown"}

    def git(*args):
        return subprocess.run(
            ["git", "-C", root, *args], capture_output=True, text=True, timeout=15
        )

    try:
        head = git("rev-parse", "--short", "HEAD")
        if head.returncode == 0:
            info["commit"] = head.stdout.strip()
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        if branch.returncode == 0:
            info["branch"] = branch.stdout.strip()
        status = git("status", "--porcelain")
        if status.returncode == 0:
            info["dirty"] = bool(status.stdout.strip())
    except Exception:
        pass  # a copy install is not a git checkout; "unknown" is the answer
    return info


def status() -> dict:
    """Everything needed to answer "will this work here?" without a console.

    Returned as plain data so the same answer can be shown in a dialog, printed
    by the CLI, or asserted in a test.
    """
    import platform

    ready = webengine_available()
    url = base_url()
    build = build_info()
    return {
        "build_commit": build["commit"],
        "build_branch": build["branch"],
        "build_dirty": build["dirty"],
        "build_path": build["path"],
        "webengine": ready,
        "cascadia_reachable": reachable(url),
        "embedding": "available" if ready else "unavailable — panel opens in the system browser",
        "base_url": url,
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
            f"  reachable:     {'yes' if data['cascadia_reachable'] else 'NO — is Cascadia running?'}",
            f"Web profile:     {data['profile_dir']}",
            f"Python:          {data['python']}",
            f"Addon build:     {data['build_commit']}"
            + (" (uncommitted edits)" if data["build_dirty"] else "")
            + f" on {data['build_branch']}",
            f"  loaded from:   {data['build_path']}",
        ]
    )


def _dock_area(value: int):
    from PySide import QtCore

    return {
        1: QtCore.Qt.LeftDockWidgetArea,
        4: QtCore.Qt.TopDockWidgetArea,
        8: QtCore.Qt.BottomDockWidgetArea,
    }.get(value, QtCore.Qt.RightDockWidgetArea)


# The live dock, cached so repeated toggles reuse one web view and one session
# rather than rebuilding (and re-authenticating) each time.
_dock = None


def _existing_dock():
    """The panel's dock, from the cache or by searching the main window."""
    global _dock
    if _dock is not None:
        try:
            _dock.objectName()  # cheap liveness probe: raises once Qt deletes it
            return _dock
        except RuntimeError:
            _dock = None

    from PySide import QtWidgets

    mw = FreeCADGui.getMainWindow()
    if mw is None:
        return None
    _dock = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    return _dock


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
        widget = existing.widget()
        if url:
            from PySide import QtCore

            _view_of(widget).load(QtCore.QUrl(target))
        return widget

    view = _build_view(target)
    prefs = _prefs()

    if as_tab:
        mdi = mw.findChild(QtWidgets.QMdiArea)
        window = mdi.addSubWindow(view)
        window.setWindowTitle("Cascadia PLM")
        window.show()
        mdi.setActiveSubWindow(window)
        return view

    global _dock
    # Parent to the main window, as FreeCAD addons conventionally do — an
    # unparented dock is owned by nothing and can be collected underneath you.
    dock = QtWidgets.QDockWidget("Cascadia PLM", mw)
    dock.setObjectName(DOCK_OBJECT_NAME)
    dock.setWidget(view)
    _dock = dock
    mw.addDockWidget(_dock_area(prefs.GetInt("DockArea", 2)), dock)
    dock.setFloating(prefs.GetBool("DockFloating", False))
    dock.resize(prefs.GetInt("DockWidth", 480), prefs.GetInt("DockHeight", 800))
    dock.dockLocationChanged.connect(_remember_placement)
    dock.visibilityChanged.connect(lambda _visible: _sync_toolbar())
    dock.show()
    _sync_toolbar()
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
    _sync_toolbar()


def _sync_toolbar() -> None:
    """Refresh the toolbar button's pressed state, if the toolbar exists."""
    if FreeCADGui is None:
        return
    try:
        from PySide import QtWidgets

        mw = FreeCADGui.getMainWindow()
        if mw is None:
            return
        toolbar = mw.findChild(QtWidgets.QToolBar, TOOLBAR_OBJECT_NAME)
        if toolbar is not None and hasattr(toolbar, "sync_checked"):
            toolbar.sync_checked()
    except Exception:
        pass


def icon_path() -> str:
    """The addon's own icon file.

    Shipped rather than looked up from an icon theme: themes are routinely
    missing (one machine here logs six absent themes at startup) and a toolbar
    button with no icon is a blank square.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "resources", "cascadia.svg")


def install_toolbar_button(main_window=None):
    """Put a Cascadia button on a toolbar owned by the main window.

    A workbench toolbar only exists while that workbench is active, so the
    button vanishes the moment an engineer switches to Part Design — which is
    most of the time. Adding the toolbar to the main window directly keeps it
    visible in every workbench, and survives interfaces that replace FreeCAD's
    own layout.

    Idempotent: repeated calls find the existing toolbar rather than stacking
    duplicates.
    """
    # Resolve the window before importing Qt: with no window there is nothing to
    # attach to, and outside FreeCAD there is no PySide to import either.
    main_window = main_window or (FreeCADGui.getMainWindow() if FreeCADGui else None)
    if main_window is None:
        return None

    from PySide import QtGui, QtWidgets

    existing = main_window.findChild(QtWidgets.QToolBar, TOOLBAR_OBJECT_NAME)
    if existing is not None:
        return existing

    toolbar = QtWidgets.QToolBar("Cascadia PLM", main_window)
    toolbar.setObjectName(TOOLBAR_OBJECT_NAME)

    icon = QtGui.QIcon(icon_path())
    action = toolbar.addAction(icon, "Cascadia PLM")
    action.setToolTip("Show or hide the Cascadia PLM panel")
    action.setStatusTip("Show or hide the Cascadia PLM panel")
    action.setCheckable(True)
    action.triggered.connect(lambda: toggle())

    def sync_checked():
        dock = _existing_dock()
        action.setChecked(bool(dock is not None and dock.isVisible()))

    # Keep the button's pressed state honest when the dock is closed by its own
    # X rather than by the button.
    toolbar.sync_checked = sync_checked
    sync_checked()

    main_window.addToolBar(toolbar)
    return toolbar


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
