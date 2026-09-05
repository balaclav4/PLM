"""Tests for the startup checker's parsing and discovery.

Two earlier attempts to start Cascadia failed on things this script now
decides: which directory is the checkout, and what DATABASE_URL actually says.
Both are string work with no feedback loop — a wrong answer does not raise, it
sends the run at the wrong database or the wrong tree and surfaces much later as
someone else's stack trace. That is what these cover.

    python tests/test_cascadia_up.py
"""

from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f" {detail}" if not condition else ""))


def load_module():
    """Import scripts/cascadia-up.py, whose name is not a Python identifier."""
    path = ROOT / "scripts" / "cascadia-up.py"
    spec = importlib.util.spec_from_file_location("cascadia_up", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cascadia_up"] = module
    spec.loader.exec_module(module)
    return module


def write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text(text)
    return target


def main() -> int:
    up = load_module()

    print("\nfinding the checkout")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        checkout = root / "PLM"
        write(checkout, "package.json", '{"name": "cascadia"}')
        nested = checkout / "cascadia-freecad" / "scripts"
        nested.mkdir(parents=True)
        check("found from a nested directory", up.find_checkout(nested) == checkout)
        check("found from the root itself", up.find_checkout(checkout) == checkout)

        # A nearer package.json belonging to something else must not win: the
        # addon ships its own tree, and so does every node package below it.
        write(nested, "package.json", '{"name": "cascadia-freecad-addon"}')
        check("a differently-named package.json is skipped", up.find_checkout(nested) == checkout)

        write(nested, "package.json", "{not json at all")
        check("malformed json is skipped, not fatal", up.find_checkout(nested) == checkout)

        elsewhere = root / "unrelated"
        elsewhere.mkdir()
        found = up.find_checkout(elsewhere)
        check("returns None when there is no checkout above", found is None, f"got {found}")

    print("\nreading DATABASE_URL")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cases = [
            ("plain", "DATABASE_URL=postgresql://u:p@localhost:5432/db", "postgresql://u:p@localhost:5432/db"),
            ("double quoted", 'DATABASE_URL="postgresql://a/b"', "postgresql://a/b"),
            ("single quoted", "DATABASE_URL='postgresql://a/b'", "postgresql://a/b"),
            ("export prefix", "export DATABASE_URL=postgresql://a/b", "postgresql://a/b"),
            ("indented", "  DATABASE_URL=postgresql://a/b", "postgresql://a/b"),
            ("trailing comment", "DATABASE_URL=postgresql://a/b  # the database", "postgresql://a/b"),
            ("after other keys", "NODE_ENV=development\nDATABASE_URL=postgresql://a/b\n", "postgresql://a/b"),
        ]
        for name, text, expected in cases:
            env = write(root, ".env", text)
            got = up.read_database_url(env)
            check(f"reads a {name} value", got == expected, f"got {got!r}")

        for name, text in [
            ("commented out", "# DATABASE_URL=postgresql://a/b"),
            ("absent", "NODE_ENV=development\n"),
            ("empty value", "DATABASE_URL=\n"),
            ("a different key ending in the same word", "POSTGRES_DATABASE_URL=postgresql://a/b"),
        ]:
            env = write(root, ".env", text)
            got = up.read_database_url(env)
            check(f"returns None when {name}", got is None, f"got {got!r}")

        check("returns None for a file that is not there", up.read_database_url(root / "nope.env") is None)

    print("\nnaming the database")
    check("plain url", up.database_name("postgresql://u:p@host:5432/cascadia") == "cascadia")
    check(
        "url with parameters",
        up.database_name("postgresql://u:p@host:5432/cascadia?sslmode=require") == "cascadia",
        up.database_name("postgresql://u:p@host:5432/cascadia?sslmode=require"),
    )
    check("underscored name survives", up.database_name("postgresql://host/my_db") == "my_db")
    check("falls back rather than returning empty", up.database_name("postgresql://host/") == "cascadia")

    print("\nthe maintenance connection")
    swapped = up.maintenance_url("postgresql://u:p@host:5432/cascadia")
    check("points at the always-present database", swapped == "postgresql://u:p@host:5432/postgres", swapped)
    check("credentials are carried over", "u:p@host:5432" in swapped)
    kept = up.maintenance_url("postgresql://u:p@host:5432/cascadia?sslmode=require")
    check("parameters are carried over", kept == "postgresql://u:p@host:5432/postgres?sslmode=require", kept)

    print("\nthe minimal .env it writes")
    check("names DATABASE_URL", "DATABASE_URL=" in up.MINIMAL_ENV)
    check("is a complete assignment", up.DEFAULT_DB_URL in up.MINIMAL_ENV)
    check("says where it came from", "cascadia-up.py" in up.MINIMAL_ENV)
    check("ends with a newline", up.MINIMAL_ENV.endswith("\n"))

    print("\nport probing")
    listener = socket.socket()
    listener.bind(("localhost", 0))
    listener.listen(1)
    bound = listener.getsockname()[1]
    check("sees a listening port", up.port_open(port=bound) is True)
    listener.close()
    check("does not see a closed one", up.port_open(port=bound, timeout=0.5) is False)

    print("\nthe embedded javascript")
    # These are JS strings living in a Python file, so nothing checks them until
    # they run against a real database. Run them against a deliberately bad URL:
    # a syntax error fails differently from a refused connection.
    checkout = up.find_checkout(ROOT)
    if checkout is None or not (checkout / "node_modules").is_dir():
        print("  SKIP  no checkout with node_modules — cannot exercise the probe")
    else:
        answer = up.node_eval(up.DB_PROBE, checkout, {"PROBE_URL": "postgresql://u:p@127.0.0.1:1/none"})
        check("the probe runs and reports a failure", answer.startswith("ERR"), answer[:90])
        check(
            "the failure is a connection one, not a javascript one",
            "SyntaxError" not in answer and "ReferenceError" not in answer,
            answer[:90],
        )
        created = up.node_eval(
            up.CREATE_DB, checkout, {"PROBE_URL": "postgresql://u:p@127.0.0.1:1/none", "PROBE_DB": "x"}
        )
        check("create-database runs and reports a failure", created.startswith("ERR"), created[:90])
        check(
            "it is not a javascript failure either",
            "SyntaxError" not in created and "ReferenceError" not in created,
            created[:90],
        )

    print("\nthe script as a program")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cascadia-up.py"), "--help"],
        capture_output=True,
        text=True,
    )
    check("--help exits cleanly", result.returncode == 0, result.stderr[-120:])
    check("--help documents --fix and --start", "--fix" in result.stdout and "--start" in result.stdout)
    missing = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cascadia-up.py"), "--checkout", tempfile.gettempdir()],
        capture_output=True,
        text=True,
    )
    check(
        "a checkout without node_modules stops with a non-zero status",
        missing.returncode != 0,
        f"exit {missing.returncode}",
    )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
