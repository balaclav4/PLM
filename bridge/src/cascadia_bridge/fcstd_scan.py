"""Answer the question that decides the project: will the agent accept our models?

The design agent refuses scripted FreeCAD documents — ``App::FeaturePython``,
Python proxies, Python-object properties — before FreeCAD is ever allowed to
open the archive. Assembly4, the fasteners workbench and most parametric addons
persist exactly those object types, so a model library built with them is
rejected wholesale. That is not a limit you can engineer around: the check *is*
the agent's trust boundary.

So measure it before building on top of it. This scanner walks a directory of
FCStd files and reports which ones would be refused, and why.

It does not reimplement the rules. It imports the agent's own
``fcstd_security`` module — pure stdlib, no FreeCAD, no database — and calls the
same function the agent calls. A reimplementation would drift from the real
behaviour the first time upstream tightened a rule, and a scanner that
disagrees with production is worse than no scanner.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

FCSTD_SUFFIXES = (".fcstd", ".fcstd1")

# Set when the agent's module is unavailable and the built-in fallback is used.
FALLBACK_NOTICE = (
    "agent module not found — used the built-in approximation. Verdicts are "
    "indicative only; re-run against a real install before deciding anything."
)


class ScannerUnavailable(RuntimeError):
    """The agent's checker could not be located and no fallback was allowed."""


def _load_agent_inspector(agent_src: Path | None) -> Callable[[bytes], Any] | None:
    """Import ``fcstd_security.inspect_fcstd_bytes`` from an agent checkout.

    Loaded by file path rather than package import so a scan works against a
    plain checkout, with no install and no dependency on the agent's package
    being importable in this interpreter.
    """
    candidates: list[Path] = []
    if agent_src:
        candidates.append(Path(agent_src))
    env = os.environ.get("MECHANICAL_DESIGN_AGENT_SRC")
    if env:
        candidates.append(Path(env))

    for root in candidates:
        for path in (
            root / "fcstd_security.py",
            root / "mechanical_design_agent" / "fcstd_security.py",
            root / "src" / "mechanical_design_agent" / "fcstd_security.py",
        ):
            if not path.exists():
                continue
            name = "_agent_fcstd_security"
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            # Register before executing: @dataclass resolves annotations through
            # sys.modules, and a module absent from it raises during class
            # creation rather than at import.
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(name, None)
                raise
            return module.inspect_fcstd_bytes

    try:  # an installed agent, if this interpreter has one
        from mechanical_design_agent.fcstd_security import (  # type: ignore[import-not-found]
            inspect_fcstd_bytes,
        )

        return inspect_fcstd_bytes
    except ImportError:
        return None


def _fallback_inspect(contents: bytes) -> Any:
    """Approximate the scripted-object rejection without the agent present.

    Deliberately crude: unzip, look for the markers the agent looks for. It
    exists so the question can be asked before the agent is installed, and it
    reports a different ``checker`` value so no one mistakes it for the real
    verdict.
    """
    import io
    import zipfile

    markers = ("featurepython", "propertypythonobject", "pythonobject", "scriptedobject")
    properties = {"proxy", "pythoncode", "pythonscript", "script", "onrestore"}

    with zipfile.ZipFile(io.BytesIO(contents)) as archive:
        names = archive.namelist()
        if "Document.xml" not in names:
            raise ValueError("FCSTD_STRUCTURE_UNSUPPORTED: FCStd has no root Document.xml")
        for name in names:
            if not name.lower().endswith(".xml"):
                continue
            text = archive.read(name).decode("utf-8", "replace").lower()
            for marker in markers:
                if marker in text:
                    raise ValueError(
                        f"FCSTD_SCRIPTED_CONTENT: scripted type marker {marker!r} in {name}"
                    )
            for prop in properties:
                if f'name="{prop}"' in text:
                    raise ValueError(
                        f"FCSTD_SCRIPTED_CONTENT: scripted property {prop!r} in {name}"
                    )
    return None


@dataclass
class FileVerdict:
    """One model's answer, with enough detail to act on."""

    path: str
    size_bytes: int
    accepted: bool
    code: str | None = None
    reason: str | None = None

    @property
    def blocking(self) -> bool:
        """True when the refusal is about scripted content rather than a malformed file."""
        return bool(self.code and "SCRIPTED" in self.code)


@dataclass
class ScanReport:
    checker: str
    scanned: int
    accepted: int
    refused: int
    by_code: dict[str, int]
    verdicts: list[FileVerdict]

    @property
    def acceptance_rate(self) -> float:
        return (self.accepted / self.scanned) if self.scanned else 0.0

    def to_json(self) -> str:
        payload = {
            "checker": self.checker,
            "scanned": self.scanned,
            "accepted": self.accepted,
            "refused": self.refused,
            "acceptance_rate": round(self.acceptance_rate, 4),
            "by_code": self.by_code,
            "verdicts": [asdict(v) for v in self.verdicts],
        }
        return json.dumps(payload, indent=2)


def iter_models(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in FCSTD_SUFFIXES:
            yield path


def scan(
    root: Path, *, agent_src: Path | None = None, allow_fallback: bool = True
) -> ScanReport:
    """Walk ``root`` and return a verdict per FCStd file."""
    inspect = _load_agent_inspector(agent_src)
    checker = "agent"
    if inspect is None:
        if not allow_fallback:
            raise ScannerUnavailable(
                "the agent's fcstd_security module was not found; pass --agent-src "
                "pointing at a checkout, or set MECHANICAL_DESIGN_AGENT_SRC"
            )
        inspect, checker = _fallback_inspect, "fallback"

    verdicts: list[FileVerdict] = []
    codes: Counter[str] = Counter()

    for path in iter_models(root):
        size = path.stat().st_size
        try:
            inspect(path.read_bytes())
            verdicts.append(FileVerdict(str(path), size, True))
        except Exception as error:  # the agent raises FcstdSecurityError; be permissive
            code, _, message = str(error).partition(": ")
            code = getattr(error, "code", code) or "UNKNOWN"
            codes[code] += 1
            verdicts.append(
                FileVerdict(str(path), size, False, code=code, reason=message.strip() or None)
            )

    accepted = sum(1 for v in verdicts if v.accepted)
    return ScanReport(
        checker=checker,
        scanned=len(verdicts),
        accepted=accepted,
        refused=len(verdicts) - accepted,
        by_code=dict(codes.most_common()),
        verdicts=verdicts,
    )


def render(report: ScanReport, *, show_all: bool = False) -> str:
    """A summary an engineer can act on, not a wall of paths."""
    lines: list[str] = []
    if report.checker == "fallback":
        lines.append(f"WARNING: {FALLBACK_NOTICE}")
        lines.append("")

    if report.scanned == 0:
        lines.append("No .FCStd files found.")
        return "\n".join(lines)

    pct = report.acceptance_rate * 100
    lines.append(f"Scanned {report.scanned} models — {report.accepted} accepted, {report.refused} refused ({pct:.1f}% usable)")
    lines.append("")

    if report.by_code:
        lines.append("Refusals by cause:")
        for code, count in report.by_code.items():
            share = count / report.scanned * 100
            lines.append(f"  {count:>5}  {share:>5.1f}%  {code}")
        lines.append("")

    refused = [v for v in report.verdicts if not v.accepted]
    scripted = [v for v in refused if v.blocking]
    if scripted:
        lines.append(
            f"{len(scripted)} refused for scripted content. These cannot be fixed by "
            "configuration — the model has to be rebuilt without Python-backed objects, "
            "or go through a STEP hand-off instead."
        )
        lines.append("")

    shown = refused if show_all else refused[:15]
    if shown:
        lines.append("Refused files:")
        for verdict in shown:
            lines.append(f"  {verdict.code:<32} {verdict.path}")
        if len(refused) > len(shown):
            lines.append(f"  ... and {len(refused) - len(shown)} more (use --all)")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="fcstd-scan",
        description="Report which FCStd models the design agent would refuse.",
    )
    parser.add_argument("path", type=Path, help="a model file or a directory to walk")
    parser.add_argument(
        "--agent-src",
        type=Path,
        help="path to an agent checkout (defaults to $MECHANICAL_DESIGN_AGENT_SRC)",
    )
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument("--all", action="store_true", help="list every refused file")
    parser.add_argument(
        "--require-agent",
        action="store_true",
        help="fail rather than fall back to the built-in approximation",
    )
    args = parser.parse_args(argv)

    try:
        report = scan(
            args.path, agent_src=args.agent_src, allow_fallback=not args.require_agent
        )
    except ScannerUnavailable as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(report.to_json() if args.json else render(report, show_all=args.all))
    return 1 if report.refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
