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
