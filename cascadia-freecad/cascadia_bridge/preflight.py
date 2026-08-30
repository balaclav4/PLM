"""Environment checks for the two things upstream can move under you.

**FreeCAD.** The agent certifies exactly one build — version 1.1.3, matched by
SHA-256 — and marks anything else ``blocked`` rather than warning. A distro
package fails even at the right version because the hash differs. Verifying the
binary here means the failure arrives at provisioning time with a clear cause,
instead of as a bootstrap diagnostic later.

**The agent's tool surface.** The agent is young and its API is still moving, so
the integration depends on its MCP tool *contract* and nothing else. Recording
that surface and diffing it turns a silent upstream rename into a failed check.

Extraction is by AST rather than by importing the server: the real module pulls
in psycopg and the MCP SDK and expects a configured workspace, none of which a
provisioning check should require.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CERTIFIED_FREECAD_VERSION = "1.1.3"
_VERSION_PATTERN = re.compile(r"\bFreeCAD(?:Cmd)?\s+(\d+\.\d+(?:\.\d+)?)\b", re.IGNORECASE)


# --- FreeCAD ---------------------------------------------------------------


@dataclass
class FreeCADCheck:
    path: str
    exists: bool
    sha256: str | None = None
    version: str | None = None
    digest_matches: bool | None = None
    version_certified: bool | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(
            self.exists
            and self.version_certified
            and (self.digest_matches is not False)
        )


def digest_of(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify_freecad(path: Path, expected_sha256: str | None = None) -> FreeCADCheck:
    """Check a FreeCADCmd binary against the version and digest the agent certifies."""
    check = FreeCADCheck(path=str(path), exists=path.exists())
    if not check.exists:
        check.notes.append("no such file — point at the official FreeCADCmd executable")
        return check

    check.sha256 = digest_of(path)
    if expected_sha256:
        check.digest_matches = check.sha256.lower() == expected_sha256.strip().lower()
        if not check.digest_matches:
            check.notes.append(
                "digest does not match the reviewed build; the agent will refuse to run it"
            )
    else:
        check.notes.append(
            "no expected digest given — record this SHA-256 in workspace config "
            "once you have verified the download"
        )

    try:
        probe = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, timeout=60
        )
        match = _VERSION_PATTERN.search(f"{probe.stdout}\n{probe.stderr}")
        check.version = match.group(1) if match else None
    except (OSError, subprocess.SubprocessError) as error:
        check.notes.append(f"version probe failed: {error}")

    if check.version is None:
        check.notes.append("could not parse a version from --version output")
        check.version_certified = False
    else:
        check.version_certified = check.version == CERTIFIED_FREECAD_VERSION
        if not check.version_certified:
            check.notes.append(
                f"version {check.version} is not certified; the agent accepts only "
                f"{CERTIFIED_FREECAD_VERSION}"
            )

    return check


# --- agent tool contract ---------------------------------------------------


def tool_surface(agent_src: Path) -> list[str]:
    """Every ``@mcp.tool()`` function name the agent's server declares."""
    server = _server_path(agent_src)
    tree = ast.parse(server.read_text(encoding="utf-8"), filename=str(server))

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                names.add(node.name)
    return sorted(names)


def _server_path(agent_src: Path) -> Path:
    for candidate in (
        agent_src / "server.py",
        agent_src / "mechanical_design_agent" / "server.py",
        agent_src / "src" / "mechanical_design_agent" / "server.py",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no mechanical_design_agent/server.py under {agent_src}")


@dataclass
class ContractDiff:
    added: list[str]
    removed: list[str]
    unchanged: int

    @property
    def ok(self) -> bool:
        """Only removals break us — a new tool is additive."""
        return not self.removed


def diff_surface(recorded: list[str], current: list[str]) -> ContractDiff:
    before, now = set(recorded), set(current)
    return ContractDiff(
        added=sorted(now - before),
        removed=sorted(before - now),
        unchanged=len(before & now),
    )


def load_snapshot(path: Path) -> list[str]:
    return list(json.loads(path.read_text())["tools"])


def save_snapshot(path: Path, tools: list[str], *, commit: str | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "note": "MCP tool surface the bridge depends on. Regenerate deliberately.",
                "agent_commit": commit,
                "tool_count": len(tools),
                "tools": tools,
            },
            indent=2,
        )
        + "\n"
    )


# --- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="cascadia-preflight",
        description="Verify FreeCAD and the design agent's tool contract.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fc = sub.add_parser("freecad", help="check a FreeCADCmd binary")
    fc.add_argument("path", type=Path)
    fc.add_argument("--expect-sha256", help="the reviewed build's digest")

    ct = sub.add_parser("contract", help="compare the agent's tool surface to a snapshot")
    ct.add_argument("agent_src", type=Path)
    ct.add_argument("--snapshot", type=Path, required=True)
    ct.add_argument("--update", action="store_true", help="rewrite the snapshot instead")
    ct.add_argument("--commit", help="agent commit to record when updating")

    args = parser.parse_args(argv)

    if args.command == "freecad":
        check = verify_freecad(args.path, args.expect_sha256)
        print(f"path     {check.path}")
        print(f"exists   {check.exists}")
        print(f"version  {check.version or 'unknown'} (certified: {check.version_certified})")
        print(f"sha256   {check.sha256 or 'n/a'}")
        if check.digest_matches is not None:
            print(f"digest   {'matches' if check.digest_matches else 'MISMATCH'}")
        for note in check.notes:
            print(f"  note: {note}")
        print(f"\n{'OK' if check.ok else 'NOT USABLE'}")
        return 0 if check.ok else 1

    tools = tool_surface(args.agent_src)
    if args.update:
        save_snapshot(args.snapshot, tools, commit=args.commit)
        print(f"recorded {len(tools)} tools to {args.snapshot}")
        return 0

    if not args.snapshot.exists():
        print(f"error: no snapshot at {args.snapshot}; run with --update first", file=sys.stderr)
        return 2

    diff = diff_surface(load_snapshot(args.snapshot), tools)
    print(f"{diff.unchanged} tools unchanged, {len(diff.added)} added, {len(diff.removed)} removed")
    for name in diff.added:
        print(f"  + {name}")
    for name in diff.removed:
        print(f"  - {name}   <-- the bridge may depend on this")
    if diff.removed:
        print("\nCONTRACT BROKEN — a tool the snapshot recorded is gone.")
        return 1
    print("\nOK" + (" (new tools available)" if diff.added else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
