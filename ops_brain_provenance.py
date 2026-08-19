"""Non-secret installation provenance for copied shared capabilities."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXCLUDED_NAMES = {".env", ".git", ".pytest_cache", "__pycache__", "reports", "assets", ".ops-brain-provenance.json"}


class ProvenanceError(RuntimeError):
    pass


def content_identity(root: Path) -> tuple[str, int]:
    if not root.is_dir() or root.is_symlink():
        raise ProvenanceError("installed capability must be a regular directory")
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def build_attestation(manifest_path: Path, capability_id: str) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [item for item in manifest.get("capabilities", []) if item.get("id") == capability_id]
    if len(matches) != 1:
        raise ProvenanceError(f"capability id is missing or ambiguous: {capability_id}")
    capability = matches[0]
    install = Path(capability["install_location"]).expanduser()
    digest, count = content_identity(install)
    return {
        "schema_version": 1,
        "capability_id": capability_id,
        "declared_source": capability["source"],
        "declared_pinned_commit": capability["pinned_commit"],
        "install_location": str(install.resolve()),
        "attested_at": datetime.now(timezone.utc).isoformat(),
        "installed_content_sha256": digest,
        "hashed_file_count": count,
        "excluded_sensitive_names": sorted(EXCLUDED_NAMES),
        "git_identity_status": "DECLARED_UNVERIFIED_INSTALLED_COPY",
        "git_identity_note": "The copied installation has no .git metadata; content identity does not prove equality to the declared commit.",
    }


def write_attestation(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
