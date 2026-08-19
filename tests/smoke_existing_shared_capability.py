#!/usr/bin/env python3
"""Read-only authority smoke in an existing Unicode customer workspace."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
registry = json.loads((ROOT / ".ops-brain" / "clients.json").read_text(encoding="utf-8"))
clients = [item for item in registry["clients"] if item.get("status") == "active" and not item["id"].isascii()]
if not clients:
    raise SystemExit("no active Unicode customer found")
client = next((item for item in clients if item["id"] == "小红书一号测试客户"), clients[0])
workspace = Path(client["workspace"])

def snapshot() -> list[tuple[str, int, int, str]]:
    items = []
    for path in sorted(workspace.rglob("*")):
        stat = path.lstat()
        digest = ""
        if path.is_file() and not path.is_symlink():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        items.append((str(path.relative_to(workspace)), stat.st_size, stat.st_mtime_ns, digest))
    return items

before = snapshot()
process = subprocess.run(
    [
        "/home/rong/.local/bin/claude-deepseek",
        "--setting-sources", "project",
        "--plugin-dir", str(ROOT / "runtime" / "ops-brain-runtime"),
        "--agent", "ops-brain-runtime:ops-brain-core",
        "--disable-slash-commands",
        "--add-dir", "/home/rong/tools/cheat-on-content",
        "--add-dir", "/home/rong/.claude/skills/social-account-doctor/scripts",
        "--add-dir", "/home/rong/.claude/skills/social-account-doctor/references",
        "--disallowedTools", "Write,Edit,Bash,WebFetch,WebSearch",
        "--no-session-persistence",
        "--max-budget-usd", "0.15", "--output-format", "stream-json", "--verbose", "-p", "Reply OK only.",
    ],
    cwd=workspace, text=True, capture_output=True, timeout=120, check=True,
)
first = json.loads(process.stdout.splitlines()[0])
assert first["type"] == "system" and first["subtype"] == "init"
assert "social-account-doctor" not in first["skills"]
assert "Skill" not in first["tools"]
assert "ops-brain-runtime:doctor-evidence" in first["agents"]
assert snapshot() == before
print(json.dumps({
    "client_id": client["id"], "display_name": client["name"], "workspace": str(workspace),
    "root_doctor_skill_available": False,
    "root_skill_tool_available": False,
    "doctor_subagent_registered": True,
    "workspace_unchanged": True,
}, ensure_ascii=False))
