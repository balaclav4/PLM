"""End-to-end round-trip against a running Cascadia.

These are integration tests by necessity: the behaviour worth testing is the
lock discipline and version accounting, and neither exists without a real
vault. Run with a live Cascadia and an API key:

    CASCADIA_API_KEY=csc_... CASCADIA_ITEM_ID=<uuid> python tests/test_roundtrip.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cascadia_bridge import (  # noqa: E402
    Binding,
    BridgeError,
    CascadiaClient,
    CascadiaError,
    checkin,
    checkout,
    sha256_of,
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


def main() -> int:
    api_key = os.environ["CASCADIA_API_KEY"]
    item_id = os.environ["CASCADIA_ITEM_ID"]
    base_url = os.environ.get("CASCADIA_URL", "http://localhost:3000")
    client = CascadiaClient(base_url, api_key)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # A unique name per run: uploading an existing name to the same item
        # starts a parallel lineage rather than a new version, which would make
        # "the latest version" ambiguous for every later assertion.
        original = root / f"bracket-{uuid.uuid4().hex[:8]}.FCStd"
        original.write_bytes(b"PK\x03\x04FCStd-v1-original-geometry" + b"\x00" * 256)
        original_digest = sha256_of(original)

        print("\nupload")
        vault_file = client.upload(item_id, original, description="initial import")
        check("upload returns a file id", bool(vault_file.file_id), vault_file.file_id)
        check("upload starts at version 1", vault_file.version == 1, f"got {vault_file.version}")

        print("\ncheckout")
        workdir = root / "job-workspace"
        result = checkout(client, vault_file.file_id, workdir, change_order_id="ECO-1", job_id="JOB-1")
        check("working copy exists", result.path.exists())
        check(
            "downloaded bytes match what was uploaded",
            sha256_of(result.path) == original_digest,
        )
        check("sidecar written", (workdir / ".cascadia-bridge.json").exists())
        check("binding carries the eco", result.binding.change_order_id == "ECO-1")
        check("binding carries the job", result.binding.job_id == "JOB-1")

        status = client.lock_status(vault_file.file_id)
        check(
            "vault reports the file locked",
            bool(status.get("isCheckedOut") or status.get("isLocked") or status.get("lockedBy")),
            str(status),
        )

        print("\ndouble checkout is refused")
        try:
            checkout(client, vault_file.file_id, root / "second-workspace")
            check("second checkout rejected", False, "it succeeded")
        except (CascadiaError, BridgeError):
            check("second checkout rejected", True)

        print("\ncheckin with no edit")
        unchanged = checkin(client, workdir)
        check("no-op reports unchanged", unchanged.changed is False)
        check("no-op mints no version", unchanged.new_version == result.binding.vault_version)
        check("sidecar cleared", not (workdir / ".cascadia-bridge.json").exists())

        print("\ncheckin with a real edit")
        again = checkout(client, vault_file.file_id, workdir)
        check("checkout resolved to the head version", again.binding.file_id == client.latest_version(vault_file.file_id).file_id)
        edited = workdir / again.binding.file_name
        edited.write_bytes(b"PK\x03\x04FCStd-v2-modified-geometry" + b"\xff" * 512)
        edited_digest = sha256_of(edited)

        changed = checkin(client, workdir, description="fillet added by design agent")
        check("edit reports changed", changed.changed is True)
        check("new sha recorded", changed.new_sha256 == edited_digest)
        check(
            "version advanced",
            changed.new_version is not None and changed.new_version > again.binding.vault_version,
            f"{again.binding.vault_version} -> {changed.new_version}",
        )

        print("\nvault reflects the new version")
        head = client.latest_version(vault_file.file_id)
        check(
            "head advanced to the new version",
            head.version == changed.new_version and head.file_id == changed.head_file_id,
            f"head=v{head.version}/{head.file_id[:8]} expected v{changed.new_version}/{changed.head_file_id[:8]}",
        )
        check("vault digest matches what we pushed", head.sha256 == edited_digest)
        redownload = root / "verify.FCStd"
        client.download(head.file_id, redownload)
        check("downloaded content is the edited content", sha256_of(redownload) == edited_digest)

        print("\nlock released after checkin")
        final_status = client.lock_status(changed.head_file_id)
        check(
            "file is no longer locked",
            not (final_status.get("isCheckedOut") or final_status.get("isLocked")),
            str(final_status),
        )

        print("\nguard rails")
        try:
            checkin(client, root / "never-checked-out")
            check("checkin without a sidecar is refused", False, "it succeeded")
        except BridgeError:
            check("checkin without a sidecar is refused", True)

        third = checkout(client, changed.head_file_id, workdir)
        try:
            checkin(client, workdir, allow_unchanged=False)
            check("require-changes rejects a no-op", False, "it succeeded")
        except BridgeError:
            check("require-changes rejects a no-op", True)
        finally:
            client.checkin(third.binding.file_id)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
