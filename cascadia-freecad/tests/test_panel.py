"""Tests for the FreeCAD panel that can run without FreeCAD.

The Qt half needs a running FreeCAD and is exercised by hand. What is testable
here is everything that decides *where the panel points* — URL resolution, the
item-type to route mapping, and reading a bridge sidecar — which is where a
silent 404 would come from.

    python bridge/tests/test_panel.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cascadia_bridge import panel  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f" {detail}" if not condition else ""))


# Routes verified to exist in packages/core/src/routes as <segment>/$id.tsx.
# Cascadia has no /items/<id> route, so a bare item id must be routed by type.
EXPECTED_SEGMENTS = {
    "parts", "documents", "change-orders", "requirements", "tasks", "issues",
    "test-plans", "test-cases", "work-instructions", "work-orders",
    "physical-parts", "tools",
}


def main() -> int:
    print("\nimports cleanly outside FreeCAD")
    check("module imported", panel is not None)
    check("FreeCAD absence is tolerated", panel.FreeCAD is None)
    check("webengine probe returns a bool", isinstance(panel.webengine_available(), bool))

    print("\nurl resolution")
    os.environ.pop("CASCADIA_URL", None)
    check("falls back to the default", panel.base_url() == "http://localhost:3000")
    os.environ["CASCADIA_URL"] = "https://plm.example.com/"
    check("environment wins", panel.base_url() == "https://plm.example.com")
    check("trailing slash is trimmed", not panel.base_url().endswith("/"))
    os.environ.pop("CASCADIA_URL", None)

    print("\nitem routing")
    check(
        "every mapped route is one that exists",
        set(panel.ITEM_ROUTES.values()) == EXPECTED_SEGMENTS,
        str(set(panel.ITEM_ROUTES.values()) ^ EXPECTED_SEGMENTS),
    )
    check("parts is the default type", panel.ITEM_ROUTES["Part"] == "parts")
    check(
        "no route points at the non-existent /items",
        "items" not in panel.ITEM_ROUTES.values(),
    )
    try:
        panel.show_item("abc", "NotAType")
        check("an unknown item type is rejected", False, "it was accepted")
    except ValueError:
        check("an unknown item type is rejected", True)

    print("\nstatus report (replaces needing a Python console)")
    data = panel.status()
    for key in ("webengine", "embedding", "base_url", "url_source", "in_freecad", "python", "cascadia_reachable"):
        check(f"status reports {key}", key in data)
    check("status knows FreeCAD is absent here", data["in_freecad"] is False)
    check("status agrees with the probe", data["webengine"] == panel.webengine_available())
    text = panel.status_text()
    check("status_text renders every line", text.count("\n") >= 5, repr(text[:60]))
    check("status_text names the URL", panel.base_url() in text)

    os.environ["CASCADIA_URL"] = "http://from-env:3000"
    check("status attributes an env URL", "environment" in panel.status()["url_source"])
    os.environ.pop("CASCADIA_URL", None)

    print("\ntoolbar button")
    import os as _os

    check("the icon path resolves", _os.path.exists(panel.icon_path()), panel.icon_path())
    check("the toolbar has a stable object name", panel.TOOLBAR_OBJECT_NAME == "CascadiaPlmToolBar")
    check("dock and toolbar names differ", panel.TOOLBAR_OBJECT_NAME != panel.DOCK_OBJECT_NAME)
    check("installing without FreeCAD is a no-op", panel.install_toolbar_button(None) is None)
    check("syncing without FreeCAD does not raise", panel._sync_toolbar() is None)

    print("\nunreachable Cascadia is explained, not dumped as a browser error")
    check("an unroutable address is not reachable", panel.reachable("http://127.0.0.1:9", timeout=1) is False)
    page = panel._unreachable_html("http://example.invalid:3000")
    check("the page names the address tried", "example.invalid:3000" in page)
    check("the page says how to run Cascadia", "npm run dev" in page)
    check("the page explains the panel does not start one", "does not start one" in page)
    check("the page mentions CASCADIA_URL", "CASCADIA_URL" in page)
    check("the page is themed for dark mode too", "prefers-color-scheme: dark" in page)

    print("\naddress bar input")
    base = "http://localhost:3000"
    cases = [
        ("/parts/1", "http://localhost:3000/parts/1", "a path stays on this instance"),
        ("parts", "http://localhost:3000/parts", "a bare word is a path, not a host"),
        ("localhost:3000/x", "http://localhost:3000/x", "host:port gets a scheme"),
        ("host.local:8080", "http://host.local:8080", "a dotted host gets a scheme"),
        ("https://a.example/y", "https://a.example/y", "a full URL is untouched"),
        ("  /bom  ", "http://localhost:3000/bom", "whitespace is trimmed"),
        ("", base, "empty goes home"),
    ]
    for typed, expected, why in cases:
        got = panel.normalize_typed_url(typed, base)
        check(why, got == expected, f"{typed!r} -> {got!r}, wanted {expected!r}")

    check(
        "a trailing slash on the base does not double up",
        panel.normalize_typed_url("/parts", "http://x:3000/") == "http://x:3000/parts",
    )

    print("\ntoolbar plumbing")
    check("the view unwrapper handles a bare widget", panel._view_of("plain") == "plain")

    class _Holder:
        web_view = "the view"

    check("the view unwrapper finds a wrapped view", panel._view_of(_Holder()) == "the view")

    class _Qt6Page:
        class WebAction:
            Back = "qt6-back"

    class _Qt5Page:
        Back = "qt5-back"

    check("web actions resolve on Qt6 scoped enums", panel._web_action(_Qt6Page, "Back") == "qt6-back")
    check("web actions resolve on Qt5 flat enums", panel._web_action(_Qt5Page, "Back") == "qt5-back")

    print("\nworking-copy deep link")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        try:
            panel.show_working_copy(workdir)
            check("a directory with no sidecar is rejected", False, "it was accepted")
        except FileNotFoundError:
            check("a directory with no sidecar is rejected", True)

        (workdir / ".cascadia-bridge.json").write_text(
            json.dumps({"item_id": "item-1", "change_order_id": "eco-1"})
        )
        binding = json.loads((workdir / ".cascadia-bridge.json").read_text())
        check(
            "an eco binding is preferred over the item",
            bool(binding.get("change_order_id")),
        )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
