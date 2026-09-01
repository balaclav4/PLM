#!/usr/bin/env python3
"""Check what Cascadia needs to run, and optionally start it.

    python scripts/cascadia-up.py           # report what is ready and what is not
    python scripts/cascadia-up.py --fix     # create .env, push schema, seed
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
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/cascadia"


def find_checkout(start: Path) -> Path | None:
    """Walk up for the Cascadia repository root.

    Identified by its package.json name, not by directory name — this addon
    normally lives inside that checkout, but need not.
    """
    import json

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fix", action="store_true", help="create .env, push schema, seed")
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

    ok = True

    print("\n[1/5] node modules")
    if (root / "node_modules").is_dir():
        print("  installed")
    else:
        ok = False
        print("  MISSING")
        if fix:
            run(["npm", "install"], root)
        else:
            print(f"  run:  cd {root} && npm install")

    print("\n[2/5] postgresql")
    if port_open():
        print("  answering on localhost:5432")
    else:
        ok = False
        print("  NOT answering on localhost:5432")
        print("  This needs root, so it is not automated. On Arch/CachyOS:")
        print("    sudo pacman -S --needed postgresql")
        print("    sudo -u postgres initdb -D /var/lib/postgres/data   # first time only")
        print("    sudo systemctl enable --now postgresql")
        print("    sudo -u postgres psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\"")
        print("    sudo -u postgres createdb cascadia")

    print("\n[3/5] .env")
    env_file = root / ".env"
    if env_file.exists():
        text = env_file.read_text()
        if "DATABASE_URL" in text:
            print("  present, with DATABASE_URL")
        else:
            ok = False
            print("  present but has no DATABASE_URL")
            print(f"  add:  DATABASE_URL={DEFAULT_DB_URL}")
    else:
        ok = False
        print("  MISSING")
        example = root / ".env.example"
        if fix and example.exists():
            shutil.copyfile(example, env_file)
            print(f"  created {env_file} from .env.example")
        else:
            print(f"  run:  cd {root} && cp .env.example .env")

    if not port_open():
        print("\nStopping here: the database steps need PostgreSQL running.")
        return 1

    print("\n[4/5] schema and seed")
    if fix:
        # db:push is interactive and will hang waiting on a prompt; the wrapper
        # takes --force, which is what the project's own db:drop:seed uses.
        if run(["node", "scripts/drizzle.mjs", "push", "--force"], root) != 0:
            print("  schema push failed — see the output above")
            return 1
        if run(["npx", "tsx", "scripts/seed-minimal.ts"], root) != 0:
            print("  seed failed — see the output above")
            return 1
    else:
        print("  not checked (needs a database connection)")
        print(f"  run:  cd {root} && node scripts/drizzle.mjs push --force")
        print(f"        cd {root} && npx tsx scripts/seed-minimal.ts")
        print("  note: 'npm run db:push' prompts and will appear to hang; use the")
        print("        --force form above")

    print("\n[5/5] dev server")
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
