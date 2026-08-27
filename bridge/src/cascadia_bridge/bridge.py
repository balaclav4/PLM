"""The FCStd round-trip: Cascadia's vault <-> a design agent job working copy.

The whole integration turns on one property — a file that leaves the vault must
be recognisable when it comes back. Cascadia identifies a file by id and
version; the design agent binds its working copies by SHA-256. This module
carries both across the boundary in a sidecar written next to the file, so a
check-in can prove which vault version the work descends from.

Deliberately not done here: the agent's job workspace is created by the agent's
own tools (``design_job_working_copy_create``). This module puts bytes where
the agent expects them and reads them back — it never writes into the agent's
database, which is what keeps either side replaceable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .client import CascadiaClient, CascadiaError, sha256_of

SIDECAR_NAME = ".cascadia-bridge.json"
SIDECAR_VERSION = 1


class BridgeError(RuntimeError):
    """The round-trip cannot proceed safely."""


@dataclass
class Binding:
    """What a working copy remembers about where it came from.

    Written at checkout, read at check-in. ``sha256`` is the digest as it left
    the vault — the check-in compares against it to tell real edits from
    no-ops, and to catch a file that was replaced rather than edited.
    """

    sidecar_version: int
    file_id: str
    item_id: str
    file_name: str
    vault_version: int
    sha256: str
    checked_out_at: str
    base_url: str
    change_order_id: str | None = None
    job_id: str | None = None

    @classmethod
    def load(cls, directory: Path) -> "Binding":
        path = directory / SIDECAR_NAME
        if not path.exists():
            raise BridgeError(
                f"no {SIDECAR_NAME} in {directory} — this directory did not come from a checkout"
            )
        raw = json.loads(path.read_text())
        version = raw.get("sidecar_version")
        if version != SIDECAR_VERSION:
            raise BridgeError(
                f"sidecar version {version!r} is not supported (expected {SIDECAR_VERSION})"
            )
        known = {field for field in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in raw.items() if key in known})

    def save(self, directory: Path) -> Path:
        path = directory / SIDECAR_NAME
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return path


@dataclass
class CheckoutResult:
    binding: Binding
    path: Path


@dataclass
class CheckinResult:
    """``file_id`` is what was checked out; ``head_file_id`` is what to use next.

    They differ whenever a new version was created — Cascadia mints a new row,
    and the id that was checked out now names a superseded version.
    """

    file_id: str
    head_file_id: str
    changed: bool
    previous_sha256: str
    new_sha256: str
    new_version: int | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def checkout(
    client: CascadiaClient,
    file_id: str,
    workdir: Path,
    *,
    change_order_id: str | None = None,
    job_id: str | None = None,
) -> CheckoutResult:
    """Lock a vault file and materialise it in ``workdir`` with its binding.

    The vault lock is taken before the download so two engineers cannot both
    believe they hold the file. If anything after the lock fails, the lock is
    released — a stranded lock needs an administrator to clear, which is a
    worse failure than the one that caused it.
    """
    workdir.mkdir(parents=True, exist_ok=True)

    # A version id is not a handle on the file — resolve the head, or the work
    # would be based on a superseded revision and silently fork the lineage.
    head = client.latest_version(file_id)
    file_name = head.file_name or f"{head.file_id}.bin"

    client.checkout(head.file_id)
    try:
        destination = workdir / file_name
        client.download(head.file_id, destination)
        digest = sha256_of(destination)

        # Cascadia stores its own digest; disagreement means the bytes we hold
        # are not the bytes the vault believes it served.
        if head.sha256 and head.sha256 != digest:
            raise BridgeError(
                f"downloaded {file_name} hashes {digest[:12]} but the vault "
                f"records {head.sha256[:12]} — refusing to start work on it"
            )

        binding = Binding(
            sidecar_version=SIDECAR_VERSION,
            file_id=head.file_id,
            item_id=head.item_id,
            file_name=file_name,
            vault_version=head.version,
            sha256=digest,
            checked_out_at=_now(),
            base_url=client.base_url,
            change_order_id=change_order_id,
            job_id=job_id,
        )
        binding.save(workdir)
    except Exception:
        # Give the lock back before surfacing whatever went wrong.
        try:
            client.checkin(head.file_id)
        except CascadiaError:
            pass
        raise

    return CheckoutResult(binding=binding, path=destination)


def checkin(
    client: CascadiaClient,
    workdir: Path,
    *,
    description: str | None = None,
    allow_unchanged: bool = True,
) -> CheckinResult:
    """Return a working copy to the vault, as a new version only if it changed.

    An unchanged file releases the lock without minting a version: a design
    session that opened a part and decided against touching it should leave no
    revision trail. Set ``allow_unchanged=False`` to make that an error instead
    — useful when a caller believes work happened and wants to know if it
    silently did not.
    """
    binding = Binding.load(workdir)
    source = workdir / binding.file_name
    if not source.exists():
        raise BridgeError(
            f"{binding.file_name} is missing from {workdir} — nothing to check in"
        )

    digest = sha256_of(source)

    if digest == binding.sha256:
        if not allow_unchanged:
            raise BridgeError(
                f"{binding.file_name} is byte-identical to vault version "
                f"{binding.vault_version}; no work to check in"
            )
        client.checkin(binding.file_id)
        _clear(workdir)
        return CheckinResult(
            file_id=binding.file_id,
            head_file_id=binding.file_id,
            changed=False,
            previous_sha256=binding.sha256,
            new_sha256=digest,
            new_version=binding.vault_version,
        )

    response = client.checkin(binding.file_id, source, description=description)
    created = response.get("newVersion")
    head_file_id, new_version = binding.file_id, None
    if isinstance(created, dict):
        head_file_id = str(created.get("id") or binding.file_id)
        new_version = created.get("fileVersion")

    _clear(workdir)
    return CheckinResult(
        file_id=binding.file_id,
        head_file_id=head_file_id,
        changed=True,
        previous_sha256=binding.sha256,
        new_sha256=digest,
        new_version=int(new_version) if new_version is not None else None,
    )


def _clear(workdir: Path) -> None:
    """Drop the sidecar once the lock is released.

    Leaving it behind would let a second check-in run against a binding whose
    lock is already gone, and report a version relationship that is no longer
    true.
    """
    sidecar = workdir / SIDECAR_NAME
    if sidecar.exists():
        sidecar.unlink()
