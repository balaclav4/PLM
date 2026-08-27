"""Command line entry point.

    cascadia-bridge checkout <file-id> --into <dir> [--eco <id>] [--job <id>]
    cascadia-bridge checkin  --from <dir> [--message <text>]
    cascadia-bridge status   --from <dir>

Connection settings come from the environment so a key never lands in shell
history: ``CASCADIA_URL`` (default http://localhost:3000) and
``CASCADIA_API_KEY``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .bridge import Binding, BridgeError, checkin, checkout
from .client import CascadiaClient, CascadiaError, sha256_of


def _client() -> CascadiaClient:
    api_key = os.environ.get("CASCADIA_API_KEY")
    if not api_key:
        raise SystemExit(
            "CASCADIA_API_KEY is not set. Create a key in Cascadia under "
            "Settings > API Keys and export it before running the bridge."
        )
    return CascadiaClient(os.environ.get("CASCADIA_URL", "http://localhost:3000"), api_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascadia-bridge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    out = sub.add_parser("checkout", help="lock a vault file and copy it into a working directory")
    out.add_argument("file_id")
    out.add_argument("--into", required=True, type=Path)
    out.add_argument("--eco", help="Cascadia change order this work belongs to")
    out.add_argument("--job", help="design agent Job id this working copy belongs to")

    back = sub.add_parser("checkin", help="return a working copy to the vault")
    back.add_argument("--from", dest="workdir", required=True, type=Path)
    back.add_argument("--message", help="description recorded against the new version")
    back.add_argument(
        "--require-changes",
        action="store_true",
        help="fail instead of releasing the lock when nothing changed",
    )

    state = sub.add_parser("status", help="show what a working directory is bound to")
    state.add_argument("--from", dest="workdir", required=True, type=Path)

    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            return _status(args.workdir)

        client = _client()

        if args.command == "checkout":
            result = checkout(
                client, args.file_id, args.into, change_order_id=args.eco, job_id=args.job
            )
            print(f"checked out {result.binding.file_name} v{result.binding.vault_version}")
            print(f"  path   {result.path}")
            print(f"  sha256 {result.binding.sha256}")
            return 0

        result = checkin(
            client,
            args.workdir,
            description=args.message,
            allow_unchanged=not args.require_changes,
        )
        if result.changed:
            print(f"checked in as version {result.new_version}")
            print(f"  {result.previous_sha256[:12]} -> {result.new_sha256[:12]}")
        else:
            print("unchanged — lock released, no new version created")
        return 0

    except (BridgeError, CascadiaError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _status(workdir: Path) -> int:
    binding = Binding.load(workdir)
    source = workdir / binding.file_name
    print(f"file    {binding.file_name} ({binding.file_id})")
    print(f"item    {binding.item_id}")
    print(f"version {binding.vault_version} checked out {binding.checked_out_at}")
    if binding.change_order_id:
        print(f"eco     {binding.change_order_id}")
    if binding.job_id:
        print(f"job     {binding.job_id}")
    if source.exists():
        digest = sha256_of(source)
        print(f"state   {'modified' if digest != binding.sha256 else 'unchanged'}")
    else:
        print("state   MISSING — the working copy is gone but the vault lock is still held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
