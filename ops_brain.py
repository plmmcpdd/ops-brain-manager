#!/usr/bin/env python3
"""A deliberately small, local registry for isolated Cheat workspaces."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REGISTRY_VERSION = 1
DEFAULT_REGISTRY = Path(__file__).resolve().parent / ".ops-brain" / "clients.json"
UPSTREAM_RUNTIME = Path("/home/rong/tools/cheat-on-content")
VALID_STATUSES = {"active", "archived"}
VALID_ORIGINS = {"created", "attached"}


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


def client_id(name: str) -> str:
    value = re.sub(r"[^\w]+", "-", name.strip().casefold(), flags=re.UNICODE).strip("-_")
    if not value:
        raise RegistryError("客户名称必须包含字母或数字，才能生成稳定 ID。")
    return value


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
        if canonical_path(workspace_value) == path:
            raise RegistryError(f"该工作区已登记给客户：{existing.get('name', '<unknown>')}（包括归档客户）。")
    return identifier, path


def validate_registry_for_write(data: dict[str, Any]) -> None:
    """Do not persist a known-inconsistent existing registry through a write command."""
    identifiers: set[str] = set()
    names: set[str] = set()
    paths: set[str] = set()
    for index, client in enumerate(data["clients"]):
        if not isinstance(client, dict) or not all(
            isinstance(client.get(field), str) and client[field]
            for field in ("id", "name", "workspace", "status")
        ):
            raise RegistryError(f"登记册 client[{index}] 不完整；请先运行 doctor 检查。")
        if client["status"] not in VALID_STATUSES:
            raise RegistryError(f"登记册 client[{index}] 状态无效；请先运行 doctor 检查。")
        if "origin" in client and client["origin"] not in VALID_ORIGINS:
            raise RegistryError(f"登记册 client[{index}] 来源无效；请先运行 doctor 检查。")
        identifier, name, path = client["id"].casefold(), client["name"].casefold(), canonical_path(client["workspace"])
        if identifier in identifiers or name in names or path in paths:
            raise RegistryError("登记册存在重复客户或路径；请先运行 doctor 检查。")
        identifiers.add(identifier)
        names.add(name)
        paths.add(path)


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


def attach(args: argparse.Namespace) -> int:
    data = load_registry(args.registry)
    validate_registry_for_write(data)
    path = Path(args.workspace)
    if not path.is_dir():
        raise RegistryError("挂接目标必须是一个已存在的工作区目录。")
    record = add_client(data, args.name, args.workspace, "attached")
    save_registry(args.registry, data)
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


def create(args: argparse.Namespace) -> int:
    data = load_registry(args.registry)
    validate_registry_for_write(data)
    target = Path(args.workspace)
    # Validate before creating anything. This also reserves archived paths.
    validate_new_client(data, args.name, args.workspace)
    created_directory = False
    try:
        if target.exists():
            if not target.is_dir() or any(target.iterdir()):
                raise RegistryError("创建目标必须不存在或为空目录。")
        else:
            target.mkdir(parents=True)
            created_directory = True
        record = add_client(data, args.name, args.workspace, "created")
        save_registry(args.registry, data)
    except Exception as exc:
        raise _create_failure(created_directory, target, exc) from exc
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


def _doctor_record(
    client: Any, index: int, seen_ids: set[str], seen_names: set[str], seen_paths: dict[str, int]
) -> tuple[list[str], list[str]]:
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
    if real_workspace in seen_paths:
        issues.append(f"{prefix}: duplicate real workspace with client[{seen_paths[real_workspace]}]")
    else:
        seen_paths[real_workspace] = index
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
    return issues, notices


def doctor(args: argparse.Namespace) -> int:
    try:
        data = load_registry(args.registry)
    except RegistryError as exc:
        print(f"ERROR: {exc}")
        return 2
    if not args.registry.exists():
        print("OK: registry is absent; no clients are registered.")
        return 0
    issues: list[str] = []
    notices: list[str] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_paths: dict[str, int] = {}
    for index, client in enumerate(data["clients"]):
        record_issues, record_notices = _doctor_record(client, index, seen_ids, seen_names, seen_paths)
        issues.extend(record_issues)
        notices.extend(record_notices)
    for notice in notices:
        print(f"NOTICE: {notice}")
    if issues:
        for issue in issues:
            print(f"ISSUE: {issue}")
        return 1
    print(f"OK: registry is structurally valid; {len(data['clients'])} client(s) checked.")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="本地、薄层的 Cheat 客户工作区管理器")
    root.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="本项目内的登记册位置")
    commands = root.add_subparsers(dest="command", required=True)
    for name, handler in (("attach", attach), ("create", create)):
        command = commands.add_parser(name)
        command.add_argument("--name", required=True)
        command.add_argument("--workspace", required=True)
        command.set_defaults(handler=handler)
    command = commands.add_parser("list")
    command.add_argument("--all", action="store_true")
    command.set_defaults(handler=list_clients)
    for name, status in (("archive", "archived"), ("restore", "active")):
        command = commands.add_parser(name)
        command.add_argument("--client", required=True)
        command.set_defaults(handler=lambda args, target_status=status: change_status(args, target_status))
    command = commands.add_parser("show")
    command.add_argument("--client", required=True)
    command.set_defaults(handler=show)
    command = commands.add_parser("open")
    command.add_argument("--client", required=True)
    command.add_argument("--app", help="显式启动的程序，例如 code")
    command.set_defaults(handler=open_workspace)
    command = commands.add_parser("doctor")
    command.set_defaults(handler=doctor)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.handler(args)
    except RegistryError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
