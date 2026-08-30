"""Preflight tests: the FreeCAD gate and the agent tool contract.

A check that cannot fail is not a check, so these assert the negative cases —
a wrong version, a mismatched digest, a removed tool — as well as the happy path.

    python bridge/tests/test_preflight.py [--agent-src PATH]
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cascadia_bridge.preflight import (  # noqa: E402
    CERTIFIED_FREECAD_VERSION,
    diff_surface,
    digest_of,
    load_snapshot,
    save_snapshot,
    tool_surface,
    verify_freecad,
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f" {detail}" if not condition else ""))


def fake_freecad(path: Path, version: str) -> Path:
    """A stand-in that answers --version the way FreeCADCmd does."""
    path.write_text(f'#!/bin/sh\necho "FreeCAD {version}"\n')
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def main(argv: list[str]) -> int:
    agent_src = Path(argv[argv.index("--agent-src") + 1]) if "--agent-src" in argv else None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        print("\nfreecad gate")
        good = fake_freecad(root / "FreeCADCmd", CERTIFIED_FREECAD_VERSION)
        result = verify_freecad(good)
        check("certified version is accepted", result.ok, str(result.notes))
        check("version is parsed", result.version == CERTIFIED_FREECAD_VERSION, str(result.version))
        check("digest is computed", result.sha256 == digest_of(good))
        check(
            "a missing expected digest is called out",
            any("record this SHA-256" in note for note in result.notes),
        )

        matched = verify_freecad(good, result.sha256)
        check("a matching digest passes", matched.digest_matches is True and matched.ok)

        mismatched = verify_freecad(good, "0" * 64)
        check("a wrong digest fails", mismatched.digest_matches is False and not mismatched.ok)

        wrong = fake_freecad(root / "OldFreeCADCmd", "1.0.1")
        old = verify_freecad(wrong)
        check("an uncertified version fails", not old.ok and old.version_certified is False)
        check(
            "the failure names the certified version",
            any(CERTIFIED_FREECAD_VERSION in note for note in old.notes),
        )

        absent = verify_freecad(root / "nope")
        check("a missing binary fails cleanly", not absent.ok and not absent.exists)

        print("\ntool contract")
        if agent_src is None:
            print("  (skipped — pass --agent-src to check against a real agent)")
        else:
            tools = tool_surface(agent_src)
            check("tools are extracted", len(tools) > 50, f"found {len(tools)}")
            check("a known tool is present", "design_job_create" in tools)
            check("names are sorted and unique", tools == sorted(set(tools)))

            snapshot = root / "contract.json"
            save_snapshot(snapshot, tools, commit="abc123")
            check("snapshot round-trips", load_snapshot(snapshot) == tools)
            check(
                "snapshot records the commit",
                json.loads(snapshot.read_text())["agent_commit"] == "abc123",
            )

            same = diff_surface(tools, tools)
            check("an identical surface is ok", same.ok and not same.added and not same.removed)

            grew = diff_surface(tools, tools + ["design_new_capability"])
            check("an added tool is ok", grew.ok and grew.added == ["design_new_capability"])

            shrank = diff_surface(tools, [t for t in tools if t != "design_job_create"])
            check(
                "a removed tool breaks the contract",
                not shrank.ok and shrank.removed == ["design_job_create"],
            )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
