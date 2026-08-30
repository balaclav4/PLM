"""Scanner tests against synthesised FCStd archives.

The fixtures are minimal but structurally real: an FCStd is a ZIP with a root
``Document.xml``, and the agent's checker reads that XML. The scripted fixture
carries the object types Assembly4 and the fasteners workbench persist, which is
the case the whole scan exists to detect.

    python bridge/tests/test_fcstd_scan.py [--agent-src PATH]
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cascadia_bridge.fcstd_scan import scan  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f" {detail}" if not condition else ""))


PLAIN_DOCUMENT = """<?xml version='1.0' encoding='utf-8'?>
<Document SchemaVersion="4" ProgramVersion="1.1.3">
  <Objects Count="1">
    <Object type="Part::Feature" name="Pad" />
  </Objects>
  <ObjectData Count="1">
    <Object name="Pad">
      <Properties Count="1">
        <Property name="Label" type="App::PropertyString">
          <String value="Bracket"/>
        </Property>
      </Properties>
    </Object>
  </ObjectData>
</Document>
"""

SCRIPTED_DOCUMENT = """<?xml version='1.0' encoding='utf-8'?>
<Document SchemaVersion="4" ProgramVersion="1.1.3">
  <Objects Count="1">
    <Object type="App::FeaturePython" name="Fastener" />
  </Objects>
  <ObjectData Count="1">
    <Object name="Fastener">
      <Properties Count="1">
        <Property name="Proxy" type="App::PropertyPythonObject">
          <Python value="cPickle" module="FastenerBase"/>
        </Property>
      </Properties>
    </Object>
  </ObjectData>
</Document>
"""


def write_fcstd(path: Path, document: str | None, extra: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if document is not None:
            archive.writestr("Document.xml", document)
        archive.writestr("GuiDocument.xml", "<?xml version='1.0'?><Document/>")
        for name, payload in (extra or {}).items():
            archive.writestr(name, payload)
    return path


def main(argv: list[str]) -> int:
    agent_src = None
    if "--agent-src" in argv:
        agent_src = Path(argv[argv.index("--agent-src") + 1])

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        library = root / "library"
        (library / "nested").mkdir(parents=True)

        write_fcstd(library / "bracket.FCStd", PLAIN_DOCUMENT)
        write_fcstd(library / "plate.FCStd", PLAIN_DOCUMENT)
        write_fcstd(library / "nested" / "assembly.FCStd", SCRIPTED_DOCUMENT)
        write_fcstd(library / "headless.FCStd", None)
        (library / "notes.txt").write_text("ignored — not a model")

        print("\nscan a mixed library")
        report = scan(library, agent_src=agent_src, allow_fallback=True)
        print(f"  (checker: {report.checker})")
        check("only FCStd files are scanned", report.scanned == 4, f"scanned {report.scanned}")
        check("clean models are accepted", report.accepted == 2, f"accepted {report.accepted}")
        check("bad models are refused", report.refused == 2, f"refused {report.refused}")

        by_path = {Path(v.path).name: v for v in report.verdicts}
        check("plain Part::Feature passes", by_path["bracket.FCStd"].accepted)
        check("App::FeaturePython is refused", not by_path["assembly.FCStd"].accepted)
        check(
            "scripted refusal is flagged as blocking",
            by_path["assembly.FCStd"].blocking,
            f"code={by_path['assembly.FCStd'].code}",
        )
        check(
            "a missing Document.xml is refused but not blocking",
            not by_path["headless.FCStd"].accepted and not by_path["headless.FCStd"].blocking,
            f"code={by_path['headless.FCStd'].code}",
        )
        check("acceptance rate is reported", abs(report.acceptance_rate - 0.5) < 1e-9)
        check("refusals are grouped by code", len(report.by_code) == 2, str(report.by_code))

        print("\nnested discovery and single-file scan")
        check(
            "nested directories are walked",
            any("nested" in v.path for v in report.verdicts),
        )
        single = scan(library / "bracket.FCStd", agent_src=agent_src)
        check("a single file can be scanned", single.scanned == 1 and single.accepted == 1)

        print("\nempty directory")
        empty = scan(root / "library" / "nested" / "none", agent_src=agent_src)
        check("an empty scan is not an error", empty.scanned == 0)

        print("\njson output")
        payload = report.to_json()
        check("json carries every verdict", payload.count('"path"') == 4)
        check("json reports which checker ran", '"checker"' in payload)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
