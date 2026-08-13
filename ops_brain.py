#!/usr/bin/env python3
"""A deliberately small, local registry for isolated Cheat workspaces."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ops_brain_publishos.client import PerformanceClient
from ops_brain_publishos.config import load_config, load_token
from ops_brain_publishos.errors import PublishOSError
from ops_brain_publishos.sync import is_due, pending_content_refs, quarantine, sync_one

REGISTRY_VERSION = 1
DEFAULT_REGISTRY = Path(__file__).resolve().parent / ".ops-brain" / "clients.json"
UPSTREAM_RUNTIME = Path("/home/rong/tools/cheat-on-content")
VALID_STATUSES = {"active", "archived"}
VALID_ORIGINS = {"created", "attached"}
CAPABILITY_MANIFEST = Path(__file__).resolve().parent / "shared-capabilities" / "manifest.json"
WINDOWS_RESERVED_SEGMENTS = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class RegistryError(RuntimeError):
    pass


def canonical_path(value: str | Path) -> str:
    """Return a stable absolute real path without creating or writing anything."""
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(value))))


def is_same_or_child(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def workspace_paths_conflict(first: str, second: str) -> bool:
    """True when two real workspace paths are equal or nested in either direction."""
    return is_same_or_child(first, second) or is_same_or_child(second, first)


def client_id(name: str) -> str:
    value = re.sub(r"[^\w]+", "-", name.strip().casefold(), flags=re.UNICODE).strip("-_")
    if not value:
        raise RegistryError("客户名称必须包含字母或数字，才能生成稳定 ID。")
    if not is_safe_client_id(value):
        raise RegistryError("客户名称无法生成安全的客户 ID。")
    return value


def is_safe_client_id(value: str) -> bool:
    """True for Manager IDs that are safe as one cross-layer filesystem segment."""
    return (
        bool(re.fullmatch(r"[\w-]+", value, flags=re.UNICODE))
        and value[0] not in "-_"
        and value[-1] not in "-_"
        and value.casefold() not in WINDOWS_RESERVED_SEGMENTS
    )


def new_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "clients": []}


def load_registry(registry_path: Path) -> dict[str, Any]:
    """Load safely. A present but invalid registry is never replaced with an empty one."""
    if not registry_path.exists():
        return new_registry()
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"无法安全读取登记册 {registry_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != REGISTRY_VERSION or not isinstance(data.get("clients"), list):
        raise RegistryError("登记册结构不受支持；为保护已有数据，未写入任何内容。")
    return data


def save_registry(registry_path: Path, data: dict[str, Any]) -> None:
    """Persist via a same-directory temporary file and an atomic replacement."""
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{registry_path.name}.", suffix=".tmp", dir=registry_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, registry_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def find_client(data: dict[str, Any], selector: str) -> dict[str, Any]:
    key = selector.casefold()
    matches = [
        client for client in data["clients"]
        if isinstance(client, dict)
        and isinstance(client.get("id"), str)
        and isinstance(client.get("name"), str)
        and (client["id"].casefold() == key or client["name"].casefold() == key)
    ]
    if not matches:
        raise RegistryError(f"未找到客户：{selector}")
    if len(matches) > 1:
        raise RegistryError(f"客户标识不唯一：{selector}")
    return matches[0]


def validate_new_client(data: dict[str, Any], name: str, workspace: str) -> tuple[str, str]:
    clean_name = name.strip()
    if not clean_name:
        raise RegistryError("客户名称不能为空。")
    identifier = client_id(clean_name)
    path = canonical_path(workspace)
    for existing in data["clients"]:
        if not isinstance(existing, dict):
            raise RegistryError("登记册含有无效客户记录；请先运行 doctor 检查。")
        if not all(isinstance(existing.get(field), str) and existing[field] for field in ("id", "name", "workspace", "status")):
            raise RegistryError("登记册含有无效客户字段；请先运行 doctor 检查。")
        if existing.get("id", "").casefold() == identifier:
            raise RegistryError(f"客户 ID 已存在：{identifier}")
        if existing.get("name", "").casefold() == clean_name.casefold():
            raise RegistryError(f"客户名称已存在：{clean_name}")
        workspace_value = existing.get("workspace")
        if not isinstance(workspace_value, str):
            raise RegistryError("登记册含有无效工作区路径；请先运行 doctor 检查。")
        existing_path = canonical_path(workspace_value)
        if workspace_paths_conflict(existing_path, path):
            raise RegistryError(
                f"工作区与客户 {existing.get('name', '<unknown>')} 冲突（包括归档客户）："
                f"已有路径 {existing_path}；新路径 {path}。客户工作区不能相同或形成父子目录关系。"
            )
    return identifier, path


def validate_registry_for_write(data: dict[str, Any]) -> None:
    """Do not persist a known-inconsistent existing registry through a write command."""
    identifiers: set[str] = set()
    names: set[str] = set()
    paths: list[str] = []
    publishos_active: set[str] = set()
    for index, client in enumerate(data["clients"]):
        if not isinstance(client, dict) or not all(
            isinstance(client.get(field), str) and client[field]
            for field in ("id", "name", "workspace", "status")
        ):
            raise RegistryError(f"登记册 client[{index}] 不完整；请先运行 doctor 检查。")
        if not is_safe_client_id(client["id"]):
            raise RegistryError(f"登记册 client[{index}] 客户 ID 不是安全的单一路径段；请先运行 doctor 检查。")
        if client["status"] not in VALID_STATUSES:
            raise RegistryError(f"登记册 client[{index}] 状态无效；请先运行 doctor 检查。")
        if "origin" in client and client["origin"] not in VALID_ORIGINS:
            raise RegistryError(f"登记册 client[{index}] 来源无效；请先运行 doctor 检查。")
        identifier, name, path = client["id"].casefold(), client["name"].casefold(), canonical_path(client["workspace"])
        if identifier in identifiers or name in names or any(workspace_paths_conflict(path, existing) for existing in paths):
            raise RegistryError("登记册存在重复客户或冲突路径；请先运行 doctor 检查。")
        identifiers.add(identifier)
        names.add(name)
        paths.append(path)
        integration = client.get("integrations")
        if integration is not None:
            if not isinstance(integration, dict):
                raise RegistryError(f"登记册 client[{index}] integrations 无效；请先运行 doctor 检查。")
            publishos = integration.get("publishos")
            if publishos is not None:
                if not isinstance(publishos, dict) or not isinstance(publishos.get("enabled"), bool) or not isinstance(publishos.get("client_id"), str) or not publishos["client_id"].strip():
                    raise RegistryError(f"登记册 client[{index}] PublishOS 集成无效；请先运行 doctor 检查。")
                if client["status"] == "active" and publishos["enabled"]:
                    key = publishos["client_id"].casefold()
                    if key in publishos_active:
                        raise RegistryError("登记册存在重复 active PublishOS client ID；请先运行 doctor 检查。")
                    publishos_active.add(key)


def add_client(data: dict[str, Any], name: str, workspace: str, origin: str) -> dict[str, Any]:
    identifier, path = validate_new_client(data, name, workspace)
    record = {
        "id": identifier,
        "name": name.strip(),
        "workspace": path,
        "status": "active",
        "origin": origin,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    data["clients"].append(record)
    return record


def attach_client(args: argparse.Namespace) -> dict[str, Any]:
    data = load_registry(args.registry)
    validate_registry_for_write(data)
    path = Path(args.workspace)
    if not path.is_dir():
        raise RegistryError("挂接目标必须是一个已存在的工作区目录。")
    record = add_client(data, args.name, args.workspace, "attached")
    save_registry(args.registry, data)
    return record


def attach(args: argparse.Namespace) -> int:
    record = attach_client(args)
    print(f"已挂接 {record['name']}：{record['workspace']}")
    return 0


def _create_failure(created_directory: bool, target: Path, error: Exception) -> RegistryError:
    rollback = "not-needed"
    if created_directory:
        try:
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()
                rollback = "completed"
            else:
                rollback = "skipped-not-empty"
        except OSError as cleanup_error:
            rollback = f"failed ({cleanup_error})"
    return RegistryError(
        f"创建失败：{error}; directory_created={'yes' if created_directory else 'no'}; "
        f"rollback={rollback}; registry_committed=no"
    )


def create_client(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    data = load_registry(args.registry)
    validate_registry_for_write(data)
    workspace = args.workspace or str(Path(args.workspace_root) / client_id(args.name))
    target = Path(workspace)
    # Validate before creating anything. This also reserves archived paths.
    validate_new_client(data, args.name, workspace)
    created_directory = False
    try:
        if target.exists():
            if not target.is_dir() or any(target.iterdir()):
                raise RegistryError("创建目标必须不存在或为空目录。")
        else:
            target.mkdir(parents=True)
            created_directory = True
        record = add_client(data, args.name, workspace, "created")
        save_registry(args.registry, data)
    except Exception as exc:
        raise _create_failure(created_directory, target, exc) from exc
    return record, created_directory


def create(args: argparse.Namespace) -> int:
    record, created_directory = create_client(args)
    print(
        f"已创建并登记 {record['name']}：{record['workspace']} "
        f"(directory_created={'yes' if created_directory else 'no'}; registry_committed=yes)"
    )
    return 0


def list_clients(args: argparse.Namespace) -> int:
    clients = load_registry(args.registry)["clients"]
    if not args.all:
        clients = [client for client in clients if isinstance(client, dict) and client.get("status") == "active"]
    if not clients:
        print("没有符合条件的客户。")
        return 0
    for client in clients:
        print(f"{client.get('id', '<invalid>')}\t{client.get('status', '<invalid>')}\t{client.get('name', '<invalid>')}\t{client.get('workspace', '<invalid>')}")
    return 0


def json_client(client: dict[str, Any]) -> dict[str, Any]:
    """The public, machine-readable client shape; never expose Registry storage details."""
    return {
        "client_id": client.get("id"),
        "display_name": client.get("name"),
        "workspace": client.get("workspace"),
        "status": client.get("status"),
        "origin": client.get("origin", "legacy"),
    }


def resolve_launch(data: dict[str, Any], selector: str) -> dict[str, Any]:
    client = find_client(data, selector)
    workspace = client.get("workspace")
    workspace_exists = isinstance(workspace, str) and Path(workspace).is_dir()
    status = client.get("status")
    if status != "active":
        reason = "client is not active"
    elif not workspace_exists:
        reason = "workspace does not exist"
    else:
        reason = "ready"
    return {
        "launch_allowed": reason == "ready",
        "client_id": client.get("id"),
        "display_name": client.get("name"),
        "workspace": workspace,
        "workspace_exists": workspace_exists,
        "status": status,
        "reason": reason,
    }


def show(args: argparse.Namespace) -> int:
    client = find_client(load_registry(args.registry), args.client)
    print(json.dumps(client, ensure_ascii=False, indent=2))
    return 0


def change_status(args: argparse.Namespace, status: str) -> int:
    data = load_registry(args.registry)
    validate_registry_for_write(data)
    client = find_client(data, args.client)
    if client.get("status") == status:
        print(f"{client['name']} 已是 {status} 状态。")
        return 0
    client["status"] = status
    client["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_registry(args.registry, data)
    print(f"已将 {client['name']} 标为 {status}；未改动其工作区。")
    return 0


def open_workspace(args: argparse.Namespace) -> int:
    client = find_client(load_registry(args.registry), args.client)
    if client.get("status") != "active":
        raise RegistryError("客户已归档；请先显式 restore 后再打开。")
    workspace = Path(client.get("workspace", ""))
    if not workspace.is_dir():
        raise RegistryError("登记的工作区已不存在或不可访问；未启动任何程序。")
    quoted = shlex.quote(str(workspace))
    if not args.app:
        print(f"客户：{client['name']}")
        print(f"工作区：{workspace}")
        print(f"cd {quoted}")
        print(f"code {quoted}")
        print(f"cd {quoted} && claude-deepseek")
        return 0
    try:
        subprocess.Popen([args.app, str(workspace)])
    except OSError as exc:
        raise RegistryError(f"无法启动 {args.app!r}：{exc}；Registry 未修改。") from exc
    print(f"已请求用 {args.app} 打开 {client['name']}：{workspace}")
    return 0


def _publishos_mapping(client: dict[str, Any]) -> str | None:
    integration = client.get("integrations", {}).get("publishos") if isinstance(client.get("integrations"), dict) else None
    if isinstance(integration, dict) and integration.get("enabled") is True and isinstance(integration.get("client_id"), str) and integration["client_id"].strip():
        return integration["client_id"].strip()
    return None


def publishos_link(args: argparse.Namespace) -> int:
    identifier = args.publishos_client_id.strip()
    if not identifier:
        raise RegistryError("PublishOS client ID 不能为空。")
    data = load_registry(args.registry)
    validate_registry_for_write(data)
    client = find_client(data, args.client)
    old = _publishos_mapping(client)
    for other in data["clients"]:
        if other is not client and other.get("status") == "active" and _publishos_mapping(other) and _publishos_mapping(other).casefold() == identifier.casefold():
            raise RegistryError("该 PublishOS client ID 已关联到另一个 active 客户。")
    if old == identifier:
        print("PublishOS 映射未变化。")
        return 0
    integrations = client.setdefault("integrations", {})
    if not isinstance(integrations, dict):
        raise RegistryError("客户 integrations 无效。")
    integrations["publishos"] = {"enabled": True, "client_id": identifier}
    save_registry(args.registry, data)
    print(f"已关联 PublishOS client ID：{old or '<none>'} -> {identifier}")
    return 0


def publishos_unlink(args: argparse.Namespace) -> int:
    data = load_registry(args.registry)
    validate_registry_for_write(data)
    client = find_client(data, args.client)
    integrations = client.get("integrations")
    if not isinstance(integrations, dict) or "publishos" not in integrations:
        print("PublishOS 映射未配置。")
        return 0
    del integrations["publishos"]
    if not integrations:
        del client["integrations"]
    save_registry(args.registry, data)
    print("已移除 PublishOS 映射；未删除客户或缓存。")
    return 0


def _manager_root(args: argparse.Namespace) -> Path:
    return Path(args.manager_root).resolve() if getattr(args, "manager_root", None) else Path(__file__).resolve().parent


def _publishos_status_data(args: argparse.Namespace) -> dict[str, Any]:
    data = load_registry(args.registry)
    clients = [client for client in data["clients"] if isinstance(client, dict)]
    if args.client:
        client = find_client(data, args.client)
        return {"client_id": client.get("id"), "display_name": client.get("name"), "status": client.get("status"), "workspace": client.get("workspace"), "publishos_enabled": bool(_publishos_mapping(client)), "publishos_client_id": _publishos_mapping(client)}
    config = load_config(_manager_root(args), profile=args.profile, config_path=args.config)
    token = load_token(_manager_root(args), config.profile)
    mappings = [_publishos_mapping(client) for client in clients if client.get("status") == "active"]
    duplicates = len(mappings) != len({value.casefold() for value in mappings if value})
    quarantine_dir = _manager_root(args) / ".ops-brain" / "quarantine" / "publishos"
    return {"profile": config.profile, "base_url": config.base_url, "verify_tls": config.verify_tls, "timeout_seconds": config.timeout_seconds, "token_configured": token.value is not None, "token_source": token.source, "linked_active_clients": len([value for value in mappings if value]), "unlinked_active_clients": len([client for client in clients if client.get("status") == "active" and not _publishos_mapping(client)]), "duplicate_mapping": duplicates, "quarantine_count": len(list(quarantine_dir.glob("*.json"))) if quarantine_dir.is_dir() else 0}


def publishos_status(args: argparse.Namespace) -> int:
    payload = _publishos_status_data(args)
    if getattr(args, "json_output", False):
        emit_json({"ok": True, "code": "ok", "data": payload, "error": None})
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def publishos_sync(args: argparse.Namespace) -> int:
    if args.content_ref and not args.client:
        raise PublishOSError("configuration_error", "--content-ref requires --client")
    data = load_registry(args.registry)
    targets = [find_client(data, args.client)] if args.client else [client for client in data["clients"] if isinstance(client, dict) and client.get("status") == "active"]
    results: list[dict[str, str]] = []
    if args.dry_run:
        for customer in targets:
            refs = [args.content_ref] if args.content_ref else pending_content_refs(Path(customer["workspace"]))
            for ref in refs:
                result = "would_request"
                if args.due and not is_due(Path(customer["workspace"]), ref, args.window_days):
                    result = "not_due"
                results.append({"client_id": customer["id"], "content_ref": ref, "result": result})
        return _emit_publishos(args, results, 0)
    config = load_config(_manager_root(args), profile=args.profile, config_path=args.config)
    token = load_token(_manager_root(args), config.profile)
    assert token.value is not None
    client = PerformanceClient(config, token.value)
    failures = 0
    for customer in targets:
        mapping = _publishos_mapping(customer)
        refs = [args.content_ref] if args.content_ref else []
        try:
            if customer.get("status") != "active":
                raise PublishOSError("archived_client", "archived customers are not synchronized")
            if not mapping:
                raise PublishOSError("not_linked", "customer has no PublishOS mapping")
            if not refs:
                refs = pending_content_refs(Path(customer["workspace"]))
            for ref in refs:
                if args.due and not is_due(Path(customer["workspace"]), ref, args.window_days):
                    results.append({"client_id": customer["id"], "content_ref": ref, "result": "not_due"})
                    continue
                result = sync_one(workspace=Path(customer["workspace"]), manager_root=_manager_root(args), profile=config.profile, ops_client_id=customer["id"], publishos_client_id=mapping, content_ref=ref, days=args.days, client=client)
                results.append({"client_id": customer["id"], "content_ref": ref, "result": result})
        except PublishOSError as exc:
            failures += 1
            quarantine(_manager_root(args), profile=config.profile, client_id=customer.get("id", "unknown"), publishos_client_id=mapping, content_ref=refs[0] if refs else args.content_ref, reason=exc.code, message=str(exc), status=exc.status)
            results.append({"client_id": customer.get("id", "unknown"), "content_ref": args.content_ref or "", "result": "quarantined"})
    return _emit_publishos(args, results, 1 if failures else 0)


def _emit_publishos(args: argparse.Namespace, results: list[dict[str, str]], status: int) -> int:
    summary = {key: sum(item["result"] == key for item in results) for key in ("updated", "no_change", "not_due", "quarantined", "would_request")}
    payload = {"ok": status == 0, "code": "ok" if status == 0 else "partial_failure", "data": {"profile": getattr(args, "profile", None) or "development", "results": results, "summary": summary}, "error": None}
    if getattr(args, "json_output", False):
        emit_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return status


def _doctor_record(client: Any, index: int, seen_ids: set[str], seen_names: set[str]) -> tuple[list[str], list[str]]:
    prefix = f"client[{index}]"
    issues: list[str] = []
    notices: list[str] = []
    if not isinstance(client, dict):
        return [f"{prefix}: record is not an object"], notices
    for field in ("id", "name", "workspace", "status"):
        if not isinstance(client.get(field), str) or not client[field]:
            issues.append(f"{prefix}: missing or invalid {field}")
    if issues:
        return issues, notices
    identifier, name, workspace, status = client["id"], client["name"], client["workspace"], client["status"]
    if not is_safe_client_id(identifier):
        issues.append(f"{prefix}: client id is not a safe single path segment: {identifier!r}")
    if identifier.casefold() in seen_ids:
        issues.append(f"{prefix}: duplicate client id {identifier}")
    seen_ids.add(identifier.casefold())
    if name.casefold() in seen_names:
        issues.append(f"{prefix}: duplicate client name {name}")
    seen_names.add(name.casefold())
    if status not in VALID_STATUSES:
        issues.append(f"{prefix}: invalid status {status}")
    if not os.path.isabs(workspace):
        issues.append(f"{prefix}: workspace is not absolute: {workspace}")
        return issues, notices
    real_workspace = canonical_path(workspace)
    if workspace != real_workspace:
        issues.append(f"{prefix}: workspace is a non-canonical or symlink alias: {workspace} -> {real_workspace}")
    if not Path(workspace).is_dir():
        issues.append(f"{prefix}: workspace does not exist: {workspace}")
    origin = client.get("origin", "legacy")
    if origin == "legacy":
        issues.append(f"{prefix}: legacy origin is unknown; confirm manually")
    elif origin not in VALID_ORIGINS:
        issues.append(f"{prefix}: invalid origin {origin}")
    elif origin == "attached" and Path(workspace).is_dir() and not (Path(workspace) / ".cheat-state.json").is_file():
        issues.append(f"{prefix}: attached workspace is missing .cheat-state.json")
    upstream = canonical_path(UPSTREAM_RUNTIME)
    if is_same_or_child(real_workspace, upstream) or is_same_or_child(upstream, real_workspace):
        issues.append(f"{prefix}: workspace and upstream runtime have a containment relationship")
    if status == "archived":
        notices.append(f"{prefix}: archived workspace remains reserved: {workspace}")
    integrations = client.get("integrations")
    if integrations is not None:
        publishos = integrations.get("publishos") if isinstance(integrations, dict) else None
        if not isinstance(integrations, dict) or (publishos is not None and (not isinstance(publishos, dict) or not isinstance(publishos.get("enabled"), bool) or not isinstance(publishos.get("client_id"), str) or not publishos["client_id"].strip())):
            issues.append(f"{prefix}: invalid PublishOS integration")
    return issues, notices


def doctor_report(registry_path: Path) -> tuple[int, dict[str, Any]]:
    try:
        data = load_registry(registry_path)
    except RegistryError as exc:
        return 2, {"ok": False, "code": "registry_error", "findings": [], "notices": [], "error": str(exc)}
    if not registry_path.exists():
        return 0, {"ok": True, "code": "ok", "findings": [], "notices": ["registry is absent; no clients are registered"], "error": None}
    issues: list[str] = []
    notices: list[str] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, client in enumerate(data["clients"]):
        record_issues, record_notices = _doctor_record(client, index, seen_ids, seen_names)
        issues.extend(record_issues)
        notices.extend(record_notices)
    publishos_mappings: dict[str, int] = {}
    for index, client in enumerate(data["clients"]):
        if isinstance(client, dict) and client.get("status") == "active":
            mapping = _publishos_mapping(client)
            if mapping:
                key = mapping.casefold()
                if key in publishos_mappings:
                    issues.append(f"client[{index}]: duplicate active PublishOS client id {mapping}")
                else:
                    publishos_mappings[key] = index
    valid_paths = [
        (index, client, canonical_path(client["workspace"]))
        for index, client in enumerate(data["clients"])
        if isinstance(client, dict)
        and isinstance(client.get("name"), str)
        and isinstance(client.get("workspace"), str)
        and os.path.isabs(client["workspace"])
    ]
    for position, (first_index, first, first_path) in enumerate(valid_paths):
        for second_index, second, second_path in valid_paths[position + 1:]:
            if workspace_paths_conflict(first_path, second_path):
                relation = "identical" if first_path == second_path else "contains"
                issues.append(
                    f"client[{first_index}] {first['name']} ({first_path}) conflicts with "
                    f"client[{second_index}] {second['name']} ({second_path}): {relation} workspace paths"
                )
    if issues:
        return 1, {"ok": False, "code": "findings", "findings": issues, "notices": notices, "error": None}
    return 0, {"ok": True, "code": "ok", "findings": [], "notices": notices, "error": None, "clients_checked": len(data["clients"])}


def doctor(args: argparse.Namespace) -> int:
    exit_code, report = doctor_report(args.registry)
    for notice in report["notices"]:
        print(f"NOTICE: {notice}")
    if exit_code == 2:
        print(f"ERROR: {report['error']}")
    elif exit_code == 1:
        for issue in report["findings"]:
            print(f"ISSUE: {issue}")
    else:
        print(f"OK: registry is structurally valid; {report.get('clients_checked', 0)} client(s) checked.")
    return exit_code


def _configured_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    configured: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", raw)
        if match:
            value = match.group(2).strip().strip("\"'")
            placeholder = any(marker in value.casefold() for marker in ("your-", "example.com", "replace-me", "change-me"))
            if value and not value.startswith("#") and not placeholder:
                configured.add(match.group(1))
    return configured


def capabilities_report(manifest_path: Path = CAPABILITY_MANIFEST) -> dict[str, Any]:
    """Inspect optional shared runtimes without changing Core doctor semantics."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reports: list[dict[str, Any]] = []
    for capability in manifest["capabilities"]:
        install = Path(capability["install_location"]).expanduser()
        config = install / capability["configuration_file"]
        configured = _configured_keys(config)
        dependencies: dict[str, str] = {}
        for dependency in capability.get("executables", []):
            if isinstance(dependency, str):
                dependency = {"id": dependency, "command": dependency}
            path = dependency.get("path")
            ready = (
                Path(path).expanduser().is_file() and os.access(Path(path).expanduser(), os.X_OK)
                if path else shutil.which(dependency["command"]) is not None
            )
            dependencies[dependency["id"]] = "READY" if ready else "MISSING"
        components: list[dict[str, str]] = []
        component_sources = capability.get("components", [])
        for component in component_sources:
            missing_keys = [key for key in component.get("config_keys", []) if key not in configured]
            missing_tools = [name for name in component.get("executables", []) if dependencies.get(name) != "READY"]
            status = "NOT_CONFIGURED" if missing_keys else ("MISSING" if missing_tools else "READY")
            components.append({"id": component["id"], "status": status})
        required_bad = any(
            item["status"] != "READY" and source.get("required", False)
            for item, source in zip(components, component_sources)
        )
        optional_bad = any(item["status"] != "READY" for item in components)
        if not (install / "SKILL.md").is_file():
            status = "MISSING"
        elif required_bad or any(value == "MISSING" for value in dependencies.values()):
            status = "DEGRADED"
        elif optional_bad:
            status = "DEGRADED"
        else:
            status = "READY"
        reports.append({
            "id": capability["id"], "display_name": capability["display_name"],
            "runtime": capability["runtime"], "status": status,
            "install_location": str(install), "pinned_commit": capability["pinned_commit"],
            "dependencies": dependencies, "components": components,
        })
    return {"core_health": "SEPARATE", "capabilities": reports}


def capabilities(args: argparse.Namespace) -> int:
    report = capabilities_report(args.manifest)
    for capability in report["capabilities"]:
        print(f"{capability['display_name']}: {capability['status']}")
        for component in capability["components"]:
            print(f"  {component['id']}: {component['status']}")
    return 0


def emit_json(payload: dict[str, Any]) -> None:
    """Windows PowerShell 5.1-safe: exactly one ASCII JSON object on stdout."""
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def run_json_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "create":
            record, _ = create_client(args)
            emit_json({"ok": True, "code": "ok", "data": json_client(record), "error": None})
            return 0
        if args.command == "attach":
            record = attach_client(args)
            emit_json({"ok": True, "code": "ok", "data": json_client(record), "error": None})
            return 0
        if args.command == "list":
            clients = load_registry(args.registry)["clients"]
            if not args.all:
                clients = [client for client in clients if isinstance(client, dict) and client.get("status") == "active"]
            emit_json({"ok": True, "code": "ok", "data": {"clients": [json_client(client) for client in clients]}, "error": None})
            return 0
        if args.command == "show":
            client = find_client(load_registry(args.registry), args.client)
            emit_json({"ok": True, "code": "ok", "data": json_client(client), "error": None})
            return 0
        if args.command == "doctor":
            exit_code, report = doctor_report(args.registry)
            emit_json({"ok": report["ok"], "code": report["code"], "data": {"findings": report["findings"], "notices": report["notices"], "clients_checked": report.get("clients_checked", 0)}, "error": report["error"]})
            if report["error"]:
                print(report["error"], file=sys.stderr)
            return exit_code
        if args.command == "resolve-launch":
            payload = resolve_launch(load_registry(args.registry), args.client)
            emit_json({"ok": True, "code": "ok", "data": payload, "error": None})
            return 0
        if args.command == "capabilities":
            emit_json({"ok": True, "code": "ok", "data": capabilities_report(args.manifest), "error": None})
            return 0
        raise RegistryError(f"JSON mode is not supported for {args.command}")
    except RegistryError as exc:
        emit_json({"ok": False, "code": "registry_error", "data": None, "error": str(exc)})
        print(str(exc), file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="本地、薄层的 Cheat 客户工作区管理器")
    root.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="本项目内的登记册位置")
    commands = root.add_subparsers(dest="command", required=True)
    for name, handler in (("attach", attach), ("create", create)):
        command = commands.add_parser(name)
        command.add_argument("--name", required=True)
        workspace_group = command.add_mutually_exclusive_group(required=True)
        workspace_group.add_argument("--workspace")
        if name == "create":
            workspace_group.add_argument("--workspace-root")
        command.add_argument("--json", dest="json_output", action="store_true")
        command.set_defaults(handler=handler)
    command = commands.add_parser("list")
    command.add_argument("--all", action="store_true")
    command.add_argument("--json", dest="json_output", action="store_true")
    command.set_defaults(handler=list_clients)
    for name, status in (("archive", "archived"), ("restore", "active")):
        command = commands.add_parser(name)
        command.add_argument("--client", required=True)
        command.set_defaults(handler=lambda args, target_status=status: change_status(args, target_status))
    command = commands.add_parser("show")
    command.add_argument("--client", required=True)
    command.add_argument("--json", dest="json_output", action="store_true")
    command.set_defaults(handler=show)
    command = commands.add_parser("open")
    command.add_argument("--client", required=True)
    command.add_argument("--app", help="显式启动的程序，例如 code")
    command.set_defaults(handler=open_workspace)
    command = commands.add_parser("doctor")
    command.add_argument("--json", dest="json_output", action="store_true")
    command.set_defaults(handler=doctor)
    command = commands.add_parser("resolve-launch")
    command.add_argument("--client", required=True)
    command.add_argument("--json", dest="json_output", action="store_true")
    command.set_defaults(handler=lambda args: 0)
    command = commands.add_parser("capabilities", help="只读检查共享能力；不影响 Core doctor")
    command.add_argument("--manifest", type=Path, default=CAPABILITY_MANIFEST)
    command.add_argument("--json", dest="json_output", action="store_true")
    command.set_defaults(handler=capabilities)
    publishos = commands.add_parser("publishos", help="只读 PublishOS 本地数据桥")
    publishos_commands = publishos.add_subparsers(dest="publishos_command", required=True)
    command = publishos_commands.add_parser("link")
    command.add_argument("--client", required=True)
    command.add_argument("--publishos-client-id", required=True)
    command.set_defaults(handler=publishos_link)
    command = publishos_commands.add_parser("unlink")
    command.add_argument("--client", required=True)
    command.set_defaults(handler=publishos_unlink)
    command = publishos_commands.add_parser("status")
    command.add_argument("--client")
    command.add_argument("--profile")
    command.add_argument("--config", type=Path)
    command.add_argument("--manager-root", type=Path)
    command.add_argument("--json", dest="json_output", action="store_true")
    command.set_defaults(handler=publishos_status)
    command = publishos_commands.add_parser("sync")
    customer = command.add_mutually_exclusive_group(required=True)
    customer.add_argument("--client")
    customer.add_argument("--all", action="store_true")
    command.add_argument("--content-ref")
    command.add_argument("--profile")
    command.add_argument("--config", type=Path)
    command.add_argument("--manager-root", type=Path)
    command.add_argument("--days", type=int, default=7, choices=range(1, 366))
    command.add_argument("--window-days", type=int, default=3, choices=range(1, 366))
    command.add_argument("--due", action="store_true")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--json", dest="json_output", action="store_true")
    command.set_defaults(handler=publishos_sync)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if getattr(args, "json_output", False):
        return run_json_command(args)
    try:
        return args.handler(args)
    except (RegistryError, PublishOSError) as exc:
        if getattr(args, "json_output", False):
            code = exc.code if isinstance(exc, PublishOSError) else "registry_error"
            emit_json({"ok": False, "code": code, "data": None, "error": str(exc)})
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
