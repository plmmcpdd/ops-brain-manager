"""Planning, customer isolation, quarantine, and one-content synchronization."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .client import PerformanceClient
from .contract import validate_response
from .errors import PublishOSError
from .report import write_report
from .storage import atomic_bytes, canonical_bytes, safe_workspace_path, validate_content_ref, write_normalized


def pending_content_refs(workspace: Path) -> list[str]:
    state_path = safe_workspace_path(workspace, ".cheat-state.json")
    if not state_path.is_file():
        raise PublishOSError("state_error", "customer state file is missing")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishOSError("state_error", "customer state file is invalid") from exc
    pending = state.get("pending_retros")
    if pending is None:
        return []
    if not isinstance(pending, list):
        raise PublishOSError("state_error", "pending_retros must be a list")
    refs: list[str] = []
    for entry in pending:
        candidate = entry.get("prediction") if isinstance(entry, dict) else entry
        if not isinstance(candidate, str):
            raise PublishOSError("state_error", "pending retro entry has no prediction path")
        prediction = safe_workspace_path(workspace, candidate)
        if not prediction.is_file():
            raise PublishOSError("prediction_missing", "pending retro prediction does not exist")
        ref = validate_content_ref(prediction.stem)
        video = safe_workspace_path(workspace, "videos", ref)
        if not video.is_dir():
            raise PublishOSError("video_missing", "required video folder does not exist")
        if ref not in refs:
            refs.append(ref)
    return refs


def is_due(workspace: Path, content_ref: str, window_days: int, now: datetime | None = None) -> bool:
    prediction = safe_workspace_path(workspace, "predictions", f"{content_ref}.md")
    if not prediction.is_file():
        raise PublishOSError("prediction_missing", "prediction does not exist")
    published = None
    for line in prediction.read_text(encoding="utf-8").splitlines()[:80]:
        if line.lower().startswith("published at:"):
            published = line.split(":", 1)[1].strip()
            break
    if not published:
        raise PublishOSError("due_error", "prediction is missing Published at")
    try:
        date = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublishOSError("due_error", "Published at is invalid") from exc
    if date.tzinfo is None:
        raise PublishOSError("due_error", "Published at requires timezone")
    return (now or datetime.now(timezone.utc)) >= date.astimezone(timezone.utc) + timedelta(days=window_days)


def quarantine(manager_root: Path, *, profile: str, client_id: str, publishos_client_id: str | None, content_ref: str | None, reason: str, message: str, status: int | None = None) -> None:
    created = datetime.now(timezone.utc)
    identity = hashlib.sha256(f"{client_id}:{content_ref}:{created.isoformat()}".encode()).hexdigest()[:12]
    record = {"version": 1, "created_at": created.isoformat(), "profile": profile, "ops_brain_client_id": client_id, "publishos_client_id": publishos_client_id, "content_ref": content_ref, "reason": reason, "safe_message": message, "http_status": status, "response_sha256": None}
    atomic_bytes(manager_root / ".ops-brain" / "quarantine" / "publishos" / f"{created.strftime('%Y%m%dT%H%M%SZ')}_{client_id}_{identity}.json", canonical_bytes(record))


def metric_decreases(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    if not previous:
        return []
    result = []
    for key, value in current["latestTotals"].items():
        old = previous.get("latestTotals", {}).get(key)
        if isinstance(old, (int, float)) and not isinstance(old, bool) and isinstance(value, (int, float)) and not isinstance(value, bool) and value < old:
            result.append(key)
    return result


def sync_one(*, workspace: Path, manager_root: Path, profile: str, ops_client_id: str, publishos_client_id: str, content_ref: str, days: int, client: PerformanceClient) -> str:
    ref = validate_content_ref(content_ref)
    latest = safe_workspace_path(workspace, ".cheat-cache", "publishos", ref, "latest.json")
    previous = None
    if latest.is_file():
        try:
            previous = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise PublishOSError("storage_error", "existing latest.json is invalid")
    payload = validate_response(client.get_performance(publishos_client_id, ref, days), publishos_client_id, ref)
    _, changed, _ = write_normalized(workspace, ref, payload)
    if not changed:
        return "no_change"
    write_report(workspace, ref, payload, decreased=metric_decreases(previous, payload))
    return "updated"
