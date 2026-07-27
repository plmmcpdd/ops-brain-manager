"""Workspace-bound atomic storage for normalized bridge data."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import PublishOSError

CONTENT_REF = re.compile(r"^[\w][\w.-]{0,180}$", re.UNICODE)


def validate_content_ref(value: str) -> str:
    if not isinstance(value, str) or not CONTENT_REF.fullmatch(value) or "/" in value or "\\" in value or value in {".", ".."}:
        raise PublishOSError("invalid_content_ref", "contentRef contains unsafe path characters")
    return value


def safe_workspace_path(workspace: Path, *parts: str) -> Path:
    root = workspace.resolve()
    target = (root.joinpath(*parts)).resolve(strict=False)
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise PublishOSError("path_escape", "path escapes the customer workspace")
    return target


def canonical_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise PublishOSError("storage_error", "atomic workspace write failed") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def write_normalized(workspace: Path, content_ref: str, payload: dict[str, Any], now: datetime | None = None) -> tuple[str, bool, Path]:
    ref = validate_content_ref(content_ref)
    base = safe_workspace_path(workspace, ".cheat-cache", "publishos", ref)
    serialized = canonical_bytes(payload)
    digest = hashlib.sha256(serialized).hexdigest()
    latest = base / "latest.json"
    if latest.exists() and latest.read_bytes() == serialized:
        return digest, False, latest
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    snapshot = base / f"{stamp}_{digest[:12]}.json"
    atomic_bytes(snapshot, serialized)
    atomic_bytes(latest, serialized)
    state = {"version": 1, "content_ref": ref, "payload_sha256": digest, "generated_at": payload["generatedAt"], "last_sync_at": (now or datetime.now(timezone.utc)).isoformat(), "result": "updated"}
    atomic_bytes(base / "sync-state.json", canonical_bytes(state))
    return digest, True, latest
