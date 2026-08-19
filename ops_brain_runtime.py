#!/usr/bin/env python3
"""Client-scoped Cheat runtime lifecycle for Ops Brain.

The client workspace is the only business-state owner.  This module validates
and scaffolds the upstream Cheat layout without copying or mutating the shared
Cheat implementation.
"""
from __future__ import annotations

import json
import os
import argparse
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LATEST_SCHEMA = "1.4"
RUNTIME_STATUSES = {"NOT_INITIALIZED", "READY", "PARTIAL", "INVALID", "NEEDS_REPAIR"}
CONTENT_FORMS = {
    "opinion-video": "opinion-video-zero.md",
    "long-essay": "long-essay-zero.md",
    "short-text": "short-text-zero.md",
    "podcast": "podcast-zero.md",
    "tutorial-builder": "tutorial-builder-zero.md",
    "other": "other-zero.md",
    "mixed": "other-zero.md",
}
REQUIRED_FILES = (
    "rubric_notes.md",
    "rubric-memo.md",
    "script_patterns.md",
    "audience.md",
    "WORKFLOW.md",
    "STATUS.md",
)
REQUIRED_DIRS = ("scripts", "predictions", "videos", "samples")
HOOK_FILES = ("prediction-immutability.sh", "session-start.sh", "log-event.sh")
CORE_MARKERS = (
    ".cheat-state.json",
    "rubric_notes.md",
    "rubric-memo.md",
    "script_patterns.md",
    "audience.md",
    "WORKFLOW.md",
    "STATUS.md",
    "predictions",
    "scripts",
    "videos",
    "samples",
    ".cheat-hooks",
)


class RuntimeLifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeProfile:
    content_form: str
    typical_duration_seconds: int | None
    cadence_days: int | None
    data_collection: str
    pool_status: str
    benchmark_status: str
    hooks: bool

    def validate(self) -> None:
        if self.content_form not in CONTENT_FORMS:
            raise RuntimeLifecycleError(f"unsupported content_form: {self.content_form}")
        if self.typical_duration_seconds is not None and self.typical_duration_seconds <= 0:
            raise RuntimeLifecycleError("typical_duration_seconds must be positive or null")
        if self.cadence_days is not None and self.cadence_days <= 0:
            raise RuntimeLifecycleError("cadence_days must be positive or null")
        if self.data_collection not in {"manual", "adapter"}:
            raise RuntimeLifecycleError("data_collection must be manual or adapter")
        if self.pool_status not in {"none", "markdown", "notion"}:
            raise RuntimeLifecycleError("pool_status must be none, markdown, or notion")
        if self.benchmark_status not in {"none", "pending"}:
            raise RuntimeLifecycleError("new runtimes support benchmark_status none or pending")


def _safe_root(path: Path) -> Path:
    if not path.is_absolute():
        raise RuntimeLifecycleError("workspace must be absolute")
    if path.is_symlink():
        raise RuntimeLifecycleError("workspace must not be a symbolic link")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise RuntimeLifecycleError("workspace must be an existing directory")
    return resolved


def _load_state(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "state root must be an object"
    return value, None


def inspect_runtime(workspace: Path) -> dict[str, Any]:
    """Read-only classification of one client workspace."""
    try:
        root = _safe_root(workspace)
    except RuntimeLifecycleError as exc:
        return {"status": "INVALID", "workspace": str(workspace), "state_path": str(workspace / ".cheat-state.json"), "issues": [str(exc)]}

    present = [name for name in CORE_MARKERS if (root / name).exists() or (root / name).is_symlink()]
    state_path = root / ".cheat-state.json"
    if not present:
        return {"status": "NOT_INITIALIZED", "workspace": str(root), "state_path": str(state_path), "issues": ["Cheat runtime state is absent"]}
    if state_path.is_symlink():
        return {"status": "INVALID", "workspace": str(root), "state_path": str(state_path), "issues": ["state file must not be a symbolic link"]}
    if not state_path.is_file():
        return {"status": "PARTIAL", "workspace": str(root), "state_path": str(state_path), "issues": [".cheat-state.json is missing while other Cheat artifacts exist"]}

    state, error = _load_state(state_path)
    if error:
        return {"status": "INVALID", "workspace": str(root), "state_path": str(state_path), "issues": [f"invalid state JSON: {error}"]}
    assert state is not None
    issues: list[str] = []
    repairable: list[str] = []
    schema = state.get("schema_version")
    if not isinstance(schema, str):
        issues.append("state.schema_version is missing or invalid")
    elif schema != LATEST_SCHEMA:
        repairable.append(f"state schema {schema} requires upstream migration to {LATEST_SCHEMA}")
    if state.get("content_form") not in CONTENT_FORMS:
        issues.append("state.content_form is missing or unsupported")
    for field in ("rubric_version", "data_collection", "pool_status", "data_layer", "initialized_at"):
        if not isinstance(state.get(field), str) or not state[field]:
            issues.append(f"state.{field} is missing or invalid")
    for field in ("calibration_samples", "benchmark_sample_count", "last_trends_added_count"):
        if not isinstance(state.get(field), int) or isinstance(state.get(field), bool) or state[field] < 0:
            issues.append(f"state.{field} is missing or invalid")
    for field in ("pending_retros", "shoots", "consecutive_directional_errors", "enabled_trend_sources", "enabled_perf_adapters"):
        if not isinstance(state.get(field), list):
            issues.append(f"state.{field} is missing or invalid")
    if not isinstance(state.get("hooks_installed"), bool):
        issues.append("state.hooks_installed is missing or invalid")

    for relative in REQUIRED_FILES:
        target = root / relative
        if target.is_symlink():
            issues.append(f"{relative} must be client-owned, not a symbolic link")
        elif not target.is_file():
            repairable.append(f"missing required file: {relative}")
    for relative in REQUIRED_DIRS:
        target = root / relative
        if target.is_symlink():
            issues.append(f"{relative}/ must be client-owned, not a symbolic link")
        elif not target.is_dir():
            repairable.append(f"missing required directory: {relative}/")
    if state.get("benchmark_status") in {"pending", "imported"} and not (root / "benchmark.md").is_file():
        repairable.append("missing benchmark.md for configured benchmark status")
    if state.get("hooks_installed") is True:
        settings = root / ".claude" / "settings.json"
        if not settings.is_file():
            repairable.append("hooks enabled but .claude/settings.json is missing")
        for name in HOOK_FILES:
            if not (root / ".cheat-hooks" / name).is_file():
                repairable.append(f"hooks enabled but .cheat-hooks/{name} is missing")

    if issues:
        status = "INVALID"
        combined = issues + repairable
    elif repairable:
        status = "NEEDS_REPAIR" if schema == LATEST_SCHEMA else "NEEDS_REPAIR"
        combined = repairable
    else:
        status = "READY"
        combined = []
    assert status in RUNTIME_STATUSES
    return {
        "status": status,
        "workspace": str(root),
        "state_path": str(state_path),
        "schema_version": schema,
        "rubric_version": state.get("rubric_version"),
        "calibration_samples": state.get("calibration_samples"),
        "hooks_installed": state.get("hooks_installed"),
        "issues": combined,
    }


def _state_for(profile: RuntimeProfile) -> dict[str, Any]:
    return {
        "schema_version": LATEST_SCHEMA,
        "skill_version": "1.0.0",
        "rubric_version": "v0",
        "content_form": profile.content_form,
        "typical_duration_seconds": profile.typical_duration_seconds,
        "target_publish_cadence_days": profile.cadence_days,
        "rubric_form_mismatch": profile.content_form != "opinion-video",
        "benchmark_status": profile.benchmark_status,
        "benchmark_name": None,
        "benchmark_sample_count": 0,
        "baseline_plays": None,
        "calibration_samples": 0,
        "calibration_samples_at_last_bump": 0,
        "data_collection": profile.data_collection,
        "pool_status": profile.pool_status,
        "data_layer": "markdown",
        "hooks_installed": profile.hooks,
        "enabled_trend_sources": ["manual-paste"],
        "enabled_perf_adapters": [],
        "last_bump_at": None,
        "last_bump_self_audited": False,
        "last_published_at": None,
        "last_published_file": None,
        "last_retro_at": None,
        "last_trends_run_at": None,
        "last_trends_added_count": 0,
        "last_prediction_self_scored": False,
        "last_self_scored_at": None,
        "consecutive_directional_errors": [],
        "pending_retros": [],
        "shoots": [],
        "in_progress_session": None,
        "initialized_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _merge_hooks(upstream: Path, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    merged: dict[str, Any] = dict(existing or {})
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RuntimeLifecycleError("existing .claude/settings.json hooks field is not an object")
    for source_name in ("prediction-immutability.json", "session-start.json", "meta-logging.json"):
        source = json.loads((upstream / "hooks" / source_name).read_text(encoding="utf-8"))
        for event, entries in source["hooks"].items():
            current = hooks.setdefault(event, [])
            if not isinstance(current, list):
                raise RuntimeLifecycleError(f"existing hook event {event} is not a list")
            for entry in entries:
                if entry not in current:
                    current.append(entry)
    return merged


def _atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _template_payloads(upstream: Path, profile: RuntimeProfile) -> dict[str, bytes]:
    mapping = {
        "rubric_notes.md": upstream / "starter-rubrics" / CONTENT_FORMS[profile.content_form],
        "rubric-memo.md": upstream / "templates" / "rubric-memo.template.md",
        "script_patterns.md": upstream / "templates" / "script_patterns.template.md",
        "audience.md": upstream / "templates" / "audience.template.md",
        "WORKFLOW.md": upstream / "templates" / "workflow.template.md",
        "STATUS.md": upstream / "templates" / "status.template.md",
    }
    if profile.benchmark_status == "pending":
        mapping["benchmark.md"] = upstream / "templates" / "benchmark.template.md"
    payloads: dict[str, bytes] = {}
    for relative, source in mapping.items():
        if not source.is_file():
            raise RuntimeLifecycleError(f"upstream template is missing: {source}")
        payloads[relative] = source.read_bytes()
    payloads[".cheat-state.json"] = (json.dumps(_state_for(profile), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return payloads


def initialize_runtime(workspace: Path, upstream: Path, profile: RuntimeProfile) -> dict[str, Any]:
    """Create a new client runtime without overwriting any Cheat-owned artifact."""
    profile.validate()
    root = _safe_root(workspace)
    upstream_root = upstream.resolve(strict=True)
    before = inspect_runtime(root)
    if before["status"] == "READY":
        return {**before, "changed": False, "message": "runtime already initialized; no files changed"}
    if before["status"] != "NOT_INITIALIZED":
        raise RuntimeLifecycleError(f"runtime is {before['status']}; use status/repair and do not reinitialize")

    payloads = _template_payloads(upstream_root, profile)
    if any((root / relative).exists() or (root / relative).is_symlink() for relative in payloads):
        raise RuntimeLifecycleError("managed-file conflict detected; initialization refused")
    if any((root / relative).exists() or (root / relative).is_symlink() for relative in REQUIRED_DIRS):
        raise RuntimeLifecycleError("managed-directory conflict detected; initialization refused")

    if profile.hooks:
        for name in HOOK_FILES:
            source = upstream_root / "hooks" / name
            if not source.is_file():
                raise RuntimeLifecycleError(f"upstream hook is missing: {source}")
            payloads[f".cheat-hooks/{name}"] = source.read_bytes()
        settings_path = root / ".claude" / "settings.json"
        existing_settings = None
        if settings_path.exists():
            if settings_path.is_symlink() or not settings_path.is_file():
                raise RuntimeLifecycleError("existing .claude/settings.json is unsafe")
            try:
                existing_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeLifecycleError(f"existing .claude/settings.json is invalid: {exc}") from exc
            if not isinstance(existing_settings, dict):
                raise RuntimeLifecycleError("existing .claude/settings.json root must be an object")
        payloads[".claude/settings.json"] = (json.dumps(_merge_hooks(upstream_root, existing_settings), ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    gitignore_path = root / ".gitignore"
    gitignore_original = gitignore_path.read_bytes() if gitignore_path.is_file() and not gitignore_path.is_symlink() else None
    if gitignore_path.exists() and gitignore_original is None:
        raise RuntimeLifecycleError("existing .gitignore is unsafe")
    template_lines = (upstream_root / "templates" / "gitignore.template").read_text(encoding="utf-8").splitlines()
    current_text = gitignore_original.decode("utf-8") if gitignore_original is not None else ""
    current_lines = current_text.splitlines()
    missing = [line for line in template_lines if line and line not in current_lines]
    suffix = ""
    if missing:
        suffix = ("\n" if current_text and not current_text.endswith("\n") else "") + "\n".join(missing) + "\n"
    payloads[".gitignore"] = (current_text + suffix).encode("utf-8")

    originals: dict[Path, bytes | None] = {}
    made_dirs: list[Path] = []
    try:
        for relative in REQUIRED_DIRS:
            target = root / relative
            target.mkdir()
            made_dirs.append(target)
            _atomic_write(target / ".gitkeep", b"")
        for relative, data in payloads.items():
            target = root / relative
            originals[target] = target.read_bytes() if target.is_file() else None
            _atomic_write(target, data, 0o755 if relative.startswith(".cheat-hooks/") else None)
    except Exception as exc:
        for target, original in reversed(list(originals.items())):
            try:
                if original is None and target.exists():
                    target.unlink()
                elif original is not None:
                    _atomic_write(target, original)
            except OSError:
                pass
        for directory in reversed(made_dirs):
            try:
                shutil.rmtree(directory)
            except OSError:
                pass
        raise RuntimeLifecycleError(f"initialization failed and rollback was attempted: {exc}") from exc

    after = inspect_runtime(root)
    if after["status"] != "READY":
        raise RuntimeLifecycleError(f"initialization completed but validation failed: {after['issues']}")
    return {**after, "changed": True, "message": "client-owned Cheat runtime initialized"}


def repair_runtime(workspace: Path, upstream: Path) -> dict[str, Any]:
    """Restore missing generated artifacts only; never reconstruct or overwrite state."""
    root = _safe_root(workspace)
    before = inspect_runtime(root)
    state_path = root / ".cheat-state.json"
    if not state_path.is_file() or state_path.is_symlink():
        raise RuntimeLifecycleError("repair requires an existing safe .cheat-state.json; no state was reconstructed")
    state, error = _load_state(state_path)
    if error or state is None:
        raise RuntimeLifecycleError("repair refuses invalid state JSON")
    if state.get("schema_version") != LATEST_SCHEMA:
        raise RuntimeLifecycleError("repair refuses schema migration; run the upstream migration flow")
    if state.get("content_form") not in CONTENT_FORMS:
        raise RuntimeLifecycleError("repair cannot select an upstream rubric for this content_form")
    profile = RuntimeProfile(
        content_form=state["content_form"],
        typical_duration_seconds=state.get("typical_duration_seconds"),
        cadence_days=state.get("target_publish_cadence_days"),
        data_collection=state.get("data_collection", "manual"),
        pool_status=state.get("pool_status", "none"),
        benchmark_status=state.get("benchmark_status", "none") if state.get("benchmark_status") in {"none", "pending"} else "pending",
        hooks=state.get("hooks_installed") is True,
    )
    payloads = _template_payloads(upstream.resolve(strict=True), profile)
    payloads.pop(".cheat-state.json")
    changed: list[str] = []
    for relative in REQUIRED_DIRS:
        target = root / relative
        if not target.exists():
            target.mkdir()
            _atomic_write(target / ".gitkeep", b"")
            changed.append(relative + "/")
    for relative, data in payloads.items():
        target = root / relative
        if not target.exists():
            _atomic_write(target, data)
            changed.append(relative)
    if profile.hooks:
        for name in HOOK_FILES:
            target = root / ".cheat-hooks" / name
            if not target.exists():
                _atomic_write(target, (upstream / "hooks" / name).read_bytes(), 0o755)
                changed.append(f".cheat-hooks/{name}")
        settings = root / ".claude" / "settings.json"
        if not settings.exists():
            _atomic_write(settings, (json.dumps(_merge_hooks(upstream.resolve(strict=True)), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            changed.append(".claude/settings.json")
    after = inspect_runtime(root)
    return {**after, "changed": bool(changed), "repaired": changed, "previous_status": before["status"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Ops Brain client runtime gate")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_runtime(args.workspace)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    elif report["status"] == "READY":
        print(f"READY: {report['state_path']}")
    else:
        print(f"{report['status']}: {'; '.join(report['issues'])}")
    return 0 if report["status"] == "READY" else 21


if __name__ == "__main__":
    raise SystemExit(main())
