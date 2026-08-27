"""Cascadia PLM REST client — the vault half of the bridge.

Only the endpoints the FCStd round-trip needs. Everything authenticates with an
API key (``Authorization: Bearer csc_...``) rather than a session cookie: the
bridge is headless, and Cascadia skips CSRF validation for token auth.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CascadiaError(RuntimeError):
    """A Cascadia API call failed.

    ``code`` is Cascadia's own error code (``NOT_FOUND``, ``VALIDATION_FAILED``,
    ...) when the response carried one. Match on that, never on ``message`` —
    the wording is not a contract.
    """

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VaultFile:
    """One *version* of a file, as Cascadia models it.

    Cascadia gives every version its own row and its own id, so ``file_id`` is
    version-scoped rather than a stable handle on the lineage. Checking a file
    in returns a different id from the one checked out — always resolve the
    head with :meth:`CascadiaClient.latest_version` before acting on "the file".
    """

    file_id: str
    file_name: str
    version: int
    size: int
    sha256: str | None = None
    is_latest: bool = True
    item_id: str = ""

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "VaultFile":
        return cls(
            file_id=str(payload["id"]),
            file_name=str(payload.get("fileName") or payload.get("originalFileName") or ""),
            version=int(payload.get("fileVersion") or 1),
            size=int(payload.get("fileSize") or 0),
            sha256=payload.get("fileHash"),
            is_latest=bool(payload.get("isLatestVersion", True)),
            item_id=str(payload.get("itemId") or ""),
        )


def sha256_of(path: Path) -> str:
    """Content digest, streamed — an assembly FCStd will not fit comfortably in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    """Encode one file plus text fields as multipart/form-data.

    Hand-rolled to keep the bridge dependency-free: it has to install cleanly
    next to the design agent without dragging a HTTP stack in behind it.
    """
    boundary = f"----cascadia{uuid.uuid4().hex}"
    sep = f"--{boundary}".encode()
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.append(
            sep
            + b"\r\n"
            + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + str(value).encode()
            + b"\r\n"
        )

    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.append(
        sep
        + b"\r\n"
        + f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode()
        + f"Content-Type: {mime}\r\n\r\n".encode()
        + file_path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())

    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class CascadiaClient:
    """Thin, synchronous client for the file endpoints the bridge uses."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -- plumbing ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        raw: bool = False,
    ) -> Any:
        url = f"{self.base_url}/api/v1{path}"
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self.api_key}")
        if content_type:
            request.add_header("Content-Type", content_type)

        # Never route loopback calls through a proxy — a configured HTTPS_PROXY
        # would otherwise swallow requests to the local Cascadia.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        try:
            with opener.open(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read()
            code, message = "HTTP_ERROR", detail.decode("utf-8", "replace")[:500]
            try:
                parsed = json.loads(detail).get("error", {})
                code = parsed.get("code", code)
                message = parsed.get("message", message)
            except (ValueError, AttributeError):
                pass
            raise CascadiaError(error.code, code, message) from error

        if raw:
            return payload
        if not payload:
            return {}
        return json.loads(payload).get("data", {})

    # -- files ------------------------------------------------------------

    def upload(
        self,
        item_id: str,
        file_path: Path,
        *,
        branch_id: str | None = None,
        description: str | None = None,
    ) -> VaultFile:
        """Attach a new file to an item, optionally in a branch (ECO) context."""
        fields: dict[str, str] = {}
        if branch_id:
            fields["branchId"] = branch_id
        if description:
            fields["file_description"] = description

        body, content_type = _multipart(fields, "file", file_path)
        data = self._request(
            "POST", f"/items/{item_id}/files/upload", body=body, content_type=content_type
        )
        files = data.get("files") or []
        if not files:
            raise CascadiaError(500, "UPLOAD_EMPTY", "upload returned no file record")
        return VaultFile.from_api(files[0])

    def metadata(self, file_id: str) -> dict[str, Any]:
        """The file record. Cascadia nests it under ``file``; callers get it flat."""
        data = self._request("GET", f"/files/{file_id}/metadata")
        return data.get("file", data)

    def latest_version(self, file_id: str) -> VaultFile:
        """Resolve any version id to the current head of its lineage.

        Checking out a superseded version would silently branch the file, so
        every path into the vault goes through here first.
        """
        for entry in self.versions(file_id):
            if entry.get("isLatestVersion"):
                head = VaultFile.from_api(entry)
                # /versions is a summary view; the full record carries itemId.
                return VaultFile.from_api({**self.metadata(head.file_id), **entry})
        return VaultFile.from_api(self.metadata(file_id))

    def lock_status(self, file_id: str) -> dict[str, Any]:
        return self._request("GET", f"/files/{file_id}/lock-status")

    def versions(self, file_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/files/{file_id}/versions")
        versions = data.get("versions", data)
        return versions if isinstance(versions, list) else []

    def checkout(self, file_id: str) -> None:
        """Take the vault lock. Raises if someone else already holds it."""
        self._request("POST", f"/files/{file_id}/checkout")

    def download(self, file_id: str, dest: Path) -> Path:
        payload = self._request("GET", f"/files/{file_id}/download", raw=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return dest

    def checkin(
        self, file_id: str, file_path: Path | None = None, description: str | None = None
    ) -> dict[str, Any]:
        """Release the lock, with a new version when ``file_path`` is given.

        Cascadia distinguishes the two by content type: multipart means a new
        version, an empty body means unlock-only.
        """
        if file_path is None:
            return self._request("POST", f"/files/{file_id}/checkin")

        fields = {"description": description} if description else {}
        body, content_type = _multipart(fields, "file", file_path)
        return self._request(
            "POST", f"/files/{file_id}/checkin", body=body, content_type=content_type
        )
