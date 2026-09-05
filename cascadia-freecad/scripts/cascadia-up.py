#!/usr/bin/env python3
"""Check what Cascadia needs to run, and optionally start it.

    python scripts/cascadia-up.py           # report what is ready and what is not
    python scripts/cascadia-up.py --fix     # write .env, create the database, push schema, seed
    python scripts/cascadia-up.py --start   # --fix, then run the dev server

The panel is a window onto a Cascadia instance and does not start one, so
something has to. This does the parts that are safe to automate and prints the
exact command for the parts that are not — installing PostgreSQL needs root, and
guessing at someone's system packages is how you break their machine.

It finds the Cascadia checkout itself rather than trusting the working
directory: running these commands from the wrong directory is the single most
common way this goes wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/cascadia"

MINIMAL_ENV = f"""\
# Written by cascadia-up.py because no .env.example was found.
DATABASE_URL={DEFAULT_DB_URL}
BASE_URL=http://localhost:3000
NODE_ENV=development
"""

# Run with cwd set to the checkout: an ESM `-e` script resolves bare specifiers
# against the working directory, which is where node_modules lives.
DB_PROBE = """
const postgres = (await import('postgres')).default
const sql = postgres(process.env.PROBE_URL, { max: 1, connect_timeout: 5, onnotice: () => {} })
try {
  await sql`select 1`
  console.log('OK')
} catch (error) {
  console.log('ERR', error.code || '-', String(error.message).replace(/\\s+/g, ' '))
} finally {
  try { await sql.end({ timeout: 1 }) } catch {}
}
"""

CREATE_DB = """
const postgres = (await import('postgres')).default
const sql = postgres(process.env.PROBE_URL, { max: 1, connect_timeout: 5, onnotice: () => {} })
try {
  await sql.unsafe('create database "' + process.env.PROBE_DB.replace(/"/g, '""') + '"')
  console.log('OK')
} catch (error) {
  console.log('ERR', error.code || '-', String(error.message).replace(/\\s+/g, ' '))
} finally {
  try { await sql.end({ timeout: 1 }) } catch {}
}
"""


def find_checkout(start: Path) -> Path | None:
    """Walk up for the Cascadia repository root.

    Identified by its package.json name, not by directory name — this addon
    normally lives inside that checkout, but need not.
    """
    for directory in [start, *start.parents]:
        manifest = directory / "package.json"
        if not manifest.exists():
            continue
        try:
            if json.loads(manifest.read_text()).get("name") == "cascadia":
                return directory
        except (ValueError, OSError):
            continue
    return None


def port_open(host: str = "localhost", port: int = 5432, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(cmd: list[str], cwd: Path, quiet: bool = False) -> int:
    if not quiet:
        print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd).returncode


def node_eval(source: str, cwd: Path, env: dict[str, str]) -> str:
    """Evaluate an ES module in the checkout, returning its last line of output."""
    try:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", source],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, **env},
        )
    except (OSError, subprocess.SubprocessError) as error:
        return f"ERR - {error}"
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    if lines:
        return lines[-1].strip()
    return "ERR - " + ((result.stderr or "").strip().splitlines() or ["no output from node"])[-1]


def read_database_url(env_file: Path) -> str | None:
    """Pull DATABASE_URL out of a .env, ignoring comments and export prefixes."""
    try:
        text = env_file.read_text()
    except OSError:
        return None
    match = re.search(r"^\s*(?:export\s+)?DATABASE_URL\s*=\s*(.*)$", text, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value or None


def database_name(url: str) -> str:
    """The database a libpq-style URL points at."""
    tail = url.rsplit("/", 1)[-1]
    return tail.split("?", 1)[0] or "cascadia"


def maintenance_url(url: str) -> str:
    """The same server, but the always-present maintenance database."""
    head, _, tail = url.rpartition("/")
    query = "?" + tail.split("?", 1)[1] if "?" in tail else ""
    return f"{head}/postgres{query}"


def print_postgres_install() -> None:
    print("  This needs root, so it is not automated. On Arch/CachyOS:")
    print("    sudo pacman -S --needed postgresql")
    print("    sudo -u postgres initdb -D /var/lib/postgres/data   # first time only")
    print("    sudo systemctl enable --now postgresql")
    print("    sudo -u postgres psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\"")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fix", action="store_true", help="write .env, create the database, push schema, seed")
    parser.add_argument("--start", action="store_true", help="--fix, then run the dev server")
    parser.add_argument("--checkout", type=Path, help="path to the Cascadia checkout")
    args = parser.parse_args(argv)
    fix = args.fix or args.start

    root = args.checkout or find_checkout(Path(__file__).resolve().parent)
    if root is None:
        print("Could not find the Cascadia checkout (a package.json naming 'cascadia').")
        print("Pass it explicitly:  python scripts/cascadia-up.py --checkout /path/to/PLM")
        return 1
    print(f"Cascadia checkout: {root}")

    if port_open(port=3000) and port_open(port=3001):
        print("\nCascadia already answers on ports 3000 and 3001 — it is running.")
        print("Open the panel in FreeCAD; nothing here needs doing.")
        return 0

    ok = True

    print("\n[1/6] node modules")
    if (root / "node_modules").is_dir():
        print("  installed")
    else:
        ok = False
        print("  MISSING")
        if fix:
            if run(["npm", "install"], root) != 0:
                print("  npm install failed — see the output above")
                return 1
        else:
            print(f"  run:  cd {root} && npm install")
            print("  (nothing below this can be checked until it is installed)")
            return 1

    print("\n[2/6] .env")
    env_file = root / ".env"
    example = root / ".env.example"
    if not env_file.exists():
        ok = False
        print("  MISSING")
        if fix and example.exists():
            shutil.copyfile(example, env_file)
            print(f"  created {env_file} from .env.example")
        elif fix:
            # No example to copy: DATABASE_URL is the only variable the app
            # truly requires, so a three-line file is a complete one.
            env_file.write_text(MINIMAL_ENV)
            print(f"  created {env_file} (no .env.example in this checkout)")
        elif example.exists():
            print(f"  run:  cd {root} && cp .env.example .env")
        else:
            print(f"  no .env.example either — run with --fix to write a minimal one")
    elif read_database_url(env_file) is None:
        ok = False
        print("  present but has no DATABASE_URL")
        if fix:
            text = env_file.read_text()
            separator = "" if text.endswith("\n") or not text else "\n"
            with env_file.open("a") as handle:
                handle.write(f"{separator}DATABASE_URL={DEFAULT_DB_URL}\n")
            print(f"  appended DATABASE_URL={DEFAULT_DB_URL}")
        else:
            print(f"  add:  DATABASE_URL={DEFAULT_DB_URL}")
    else:
        print("  present, with DATABASE_URL")

    url = read_database_url(env_file) or DEFAULT_DB_URL
    name = database_name(url)

    print("\n[3/6] postgresql")
    if port_open():
        print("  answering on localhost:5432")
    else:
        print("  NOT answering on localhost:5432")
        print_postgres_install()
        print("\nStopping here: everything below needs PostgreSQL running.")
        return 1

    # A listening port is not a usable database. The two ways this goes wrong
    # after a fresh install — the database was never created, and the postgres
    # role has no password — both surface here as a plain sentence rather than
    # as a stack trace out of drizzle several steps later.
    print(f"\n[4/6] database '{name}'")
    answer = node_eval(DB_PROBE, root, {"PROBE_URL": url})
    if answer == "OK":
        print("  connected")
    elif answer.startswith("ERR 3D000"):
        ok = False
        print(f"  does not exist on this server")
        created = False
        if fix:
            print(f"  creating it over the same connection...")
            result = node_eval(CREATE_DB, root, {"PROBE_URL": maintenance_url(url), "PROBE_DB": name})
            created = result == "OK"
            print(f"  created '{name}'" if created else f"  could not create it: {result}")
        if not created:
            print(f"  run:  sudo -u postgres createdb {name}")
            return 1
    elif answer.startswith("ERR 28P01") or answer.startswith("ERR 28000"):
        print("  the credentials in DATABASE_URL were rejected")
        print("  Either fix DATABASE_URL in .env, or set the password to match:")
        print("    sudo -u postgres psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\"")
        return 1
    else:
        print(f"  could not connect: {answer.removeprefix('ERR ').strip()}")
        return 1

    print("\n[5/6] schema and seed")
    if fix:
        # db:push is interactive and will hang waiting on a prompt; the wrapper
        # takes --force, which is what the project's own db:drop:seed uses.
        if run(["node", "scripts/drizzle.mjs", "push", "--force"], root) != 0:
            print("  schema push failed — see the output above")
            return 1
        if run(["npx", "tsx", "scripts/seed-minimal.ts"], root) != 0:
            print("  seed failed — see the output above")
            return 1
        print("\n  Sign in with  admin@cascadia.local / Cascadia")
    else:
        print("  not pushed (this run only reports)")
        print(f"  run:  cd {root} && node scripts/drizzle.mjs push --force")
        print(f"        cd {root} && npx tsx scripts/seed-minimal.ts")
        print("  note: 'npm run db:push' prompts and will appear to hang; use the")
        print("        --force form above")

    print("\n[6/6] dev server")
    if args.start:
        print("  starting — Ctrl-C to stop")
        print("  wait for BOTH lines: 'Local: http://localhost:3000/' and")
        print("  'Hono API server running on http://localhost:3001'")
        return run(["npm", "run", "dev"], root)

    print(f"  run:  cd {root} && npm run dev")
    print("  then re-open the panel in FreeCAD")

    if not ok and not fix:
        print("\nSome prerequisites are missing. Re-run with --fix to do the safe ones.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
