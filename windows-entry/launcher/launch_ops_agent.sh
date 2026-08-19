#!/usr/bin/env bash
# Dedicated, non-content-producing launcher for one customer's Claude session.
set -u

STATE_ROOT="${OPS_BRAIN_AGENT_STATE_ROOT:-/home/rong/projects/content-ops-lab/ops-brain-manager/.ops-brain/agent-sessions}"
ENV_FILE="$HOME/.config/claude-deepseek/env"
BASE_CLAUDE="${OPS_BRAIN_BASE_CLAUDE:-/home/rong/.local/bin/claude}"
SHARED_CAPABILITY_MANIFEST="${OPS_BRAIN_SHARED_CAPABILITY_MANIFEST:-/home/rong/projects/content-ops-lab/ops-brain-manager/shared-capabilities/manifest.json}"
RUNTIME_VALIDATOR="${OPS_BRAIN_RUNTIME_VALIDATOR:-/home/rong/projects/content-ops-lab/ops-brain-manager/ops_brain_runtime.py}"
AUTHORITY_PLUGIN="${OPS_BRAIN_AUTHORITY_PLUGIN:-/home/rong/projects/content-ops-lab/ops-brain-manager/runtime/ops-brain-runtime}"
PRIMARY_AGENT="${OPS_BRAIN_PRIMARY_AGENT:-ops-brain-runtime:ops-brain-core}"
export PATH="$HOME/.local/bin:$PATH"

fail() { printf 'Ops Brain Agent error: %s\n' "$1" >&2; exit "${2:-2}"; }
lock_path_for_client() {
  python3 - "$STATE_ROOT" "$1" <<'PY'
import os, re, sys
state_root, client_id = sys.argv[1:]
if not re.fullmatch(r"[\w-]+", client_id, flags=re.UNICODE) or client_id[0] in "-_" or client_id[-1] in "-_":
    raise SystemExit(2)
if client_id.casefold() in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}:
    raise SystemExit(2)
root = os.path.realpath(os.path.abspath(state_root))
lock = os.path.abspath(os.path.join(root, client_id + ".lock"))
if os.path.commonpath((root, lock)) != root or os.path.dirname(lock) != root:
    raise SystemExit(2)
print(lock)
PY
}
wait_for_file() {
  local path="$1" attempt=1
  while (( attempt <= 3 )); do
    [[ -f "$path" && -x "$path" ]] && return 0
    (( attempt < 3 )) && sleep 1
    ((attempt++))
  done
  return 1
}
run_agent_with_shared_capability_env() {
  python3 - "$SHARED_CAPABILITY_MANIFEST" "$AGENT_COMMAND" "$BOOTSTRAP_FILE" <<'PY'
import json, os, re, subprocess, sys
from pathlib import Path

allowed = re.compile(r"^(TIKHUB_API_KEY|VIDEO_ANALYSIS_[A-Z0-9_]+|AUDIO_TRANSCRIPTION_[A-Z0-9_]+)$")
env = os.environ.copy()
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for capability in manifest.get("capabilities", []):
    config = Path(capability["install_location"]).expanduser() / capability["configuration_file"]
    if not config.is_file():
        continue
    for raw in config.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if allowed.fullmatch(key):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env[key] = value
bootstrap = Path(sys.argv[3]).read_text(encoding="utf-8")
command = [
    sys.argv[2],
    "--setting-sources", "project",
    "--plugin-dir", os.environ["OPS_BRAIN_AUTHORITY_PLUGIN"],
    "--agent", os.environ["OPS_BRAIN_PRIMARY_AGENT"],
    "--append-system-prompt", bootstrap,
]
raise SystemExit(subprocess.run(command, env=env).returncode)
PY
}
validate_client_runtime() {
  [[ -f "$RUNTIME_VALIDATOR" ]] || fail 'client runtime validator is missing' 21
  python3 "$RUNTIME_VALIDATOR" --workspace "$WORKSPACE" --json >/dev/null \
    || fail 'client Cheat runtime is not READY; initialize or repair before launch' 21
}
validate_authority_runtime() {
  [[ -f "$AUTHORITY_PLUGIN/.claude-plugin/plugin.json" ]] || fail 'Ops Brain authority plugin manifest is missing' 22
  [[ -f "$AUTHORITY_PLUGIN/agents/ops-brain-core.md" ]] || fail 'Ops Brain primary agent is missing' 22
  [[ -f "$AUTHORITY_PLUGIN/agents/doctor-evidence.md" ]] || fail 'Ops Brain Doctor evidence agent is missing' 22
  [[ "$PRIMARY_AGENT" == 'ops-brain-runtime:ops-brain-core' ]] || fail 'unsupported primary agent override' 22
  export OPS_BRAIN_AUTHORITY_PLUGIN="$AUTHORITY_PLUGIN"
  export OPS_BRAIN_PRIMARY_AGENT="$PRIMARY_AGENT"
}
validate_bootstrap() {
  python3 - "$CLIENT_ID" "$WORKSPACE" "$BOOTSTRAP_FILE" <<'PY'
import sys
from pathlib import Path

client_id, workspace, raw_bootstrap = sys.argv[1:]
try:
    bootstrap = Path(raw_bootstrap)
    if not bootstrap.is_absolute() or bootstrap.name != "initial_prompt.txt":
        raise ValueError("bootstrap path must be absolute and named initial_prompt.txt")
    # The generated projection contract is .../<client_id>/.ops-launch/initial_prompt.txt.
    if bootstrap.parent.name != ".ops-launch" or bootstrap.parent.parent.name != client_id:
        raise ValueError("bootstrap path does not belong to current client")
    resolved = bootstrap.resolve(strict=True)
    if resolved != bootstrap or not resolved.is_file():
        raise ValueError("bootstrap must be a regular file without symlink indirection")
    text = resolved.read_text(encoding="utf-8")
    required = {
        "OPS_BRAIN_BOOTSTRAP v1",
        f"client_id: {client_id}",
        f"workspace: {workspace}",
        "role: Ops Brain / 运营大脑",
        "primary_core: XBuilderLAB/cheat-on-content；拥有最终运营判断权。",
        "state_entry: 当前客户 workspace/.cheat-state.json 是客户运营状态唯一事实源。",
        "boundary: 未收到用户明确任务前，不得自行执行生产动作。",
        "boundary: 不得修改全局只读 Cheat implementation；客户数据、客户状态和共享能力必须保持边界。",
    }
    if required.difference(text.splitlines()):
        raise ValueError("bootstrap client identity or required contract is invalid")
except (OSError, UnicodeError, ValueError) as error:
    print(f"OPS_BRAIN_BOOTSTRAP_FAILED: {error}", file=sys.stderr)
    raise SystemExit(20)
PY
}
lock_metadata_pid() { sed -n 's/.*"wrapper_pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$1/metadata.json" 2>/dev/null | head -n 1; }
remove_own_lock() {
  [[ -n "${LOCK_DIR:-}" && -f "$LOCK_DIR/metadata.json" ]] || return 0
  [[ "$(lock_metadata_pid "$LOCK_DIR")" == "$$" ]] && rm -rf -- "$LOCK_DIR"
}
write_metadata() {
  python3 - "$LOCK_DIR/metadata.json" "$CLIENT_ID" "$WORKSPACE" "$$" "$AGENT_COMMAND" <<'PY'
import json, sys
from datetime import datetime, timezone
path, client_id, workspace, pid, command = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({"client_id": client_id, "workspace": workspace, "wrapper_pid": int(pid), "started_at": datetime.now(timezone.utc).isoformat(), "agent_command": command}, handle, ensure_ascii=True)
    handle.write("\n")
PY
}
diagnose() {
  printf 'agent_command_exists=%s\n' "$([[ -x "$1" ]] && echo true || echo false)"
  printf 'deepseek_env_exists=%s\n' "$([[ -f "$ENV_FILE" ]] && echo true || echo false)"
  printf 'claude_exists=%s\n' "$([[ -x "$BASE_CLAUDE" ]] && echo true || echo false)"
  printf 'shared_capability_manifest_exists=%s\n' "$([[ -f "$SHARED_CAPABILITY_MANIFEST" ]] && echo true || echo false)"
  printf 'runtime_validator_exists=%s\n' "$([[ -f "$RUNTIME_VALIDATOR" ]] && echo true || echo false)"
  printf 'authority_plugin_exists=%s\n' "$([[ -f "$AUTHORITY_PLUGIN/.claude-plugin/plugin.json" ]] && echo true || echo false)"
  printf 'tikhub_exists=%s\n' "$([[ -x "$HOME/.local/bin/tikhub" ]] && echo true || echo false)"
  [[ -d "$STATE_ROOT" ]] || return 0
  for lock in "$STATE_ROOT"/*.lock; do
    [[ -d "$lock" ]] || continue
    local pid; pid="$(lock_metadata_pid "$lock")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then printf 'lock=%s status=active pid=%s\n' "$(basename "$lock" .lock)" "$pid"; else printf 'lock=%s status=stale pid=%s\n' "$(basename "$lock" .lock)" "${pid:-unknown}"; fi
  done
}
clear_stale() {
  local target="$1" lock pid
  lock="$(lock_path_for_client "$target")" || fail 'invalid client_id for session state' 2
  [[ ! -L "$lock" ]] || fail 'unsafe symbolic-link session lock' 2
  [[ -d "$lock" ]] || fail 'session lock does not exist' 3
  pid="$(lock_metadata_pid "$lock")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && fail 'active lock cannot be cleared' 4
  rm -rf -- "$lock"
  printf 'stale lock cleared for %s\n' "$target"
}

case "${1:-}" in
  --diagnose) diagnose "${2:-}"; exit 0 ;;
  --clear-stale) clear_stale "${2:-}"; exit 0 ;;
esac

[[ "$#" -eq 4 ]] || fail 'usage: launch_ops_agent.sh client_id workspace agent_command bootstrap_file'
CLIENT_ID="$1"; WORKSPACE="$2"; AGENT_COMMAND="$3"; BOOTSTRAP_FILE="$4"
LOCK_DIR="$(lock_path_for_client "$CLIENT_ID")" || fail 'invalid client_id' 2
[[ ! -L "$LOCK_DIR" ]] || fail 'unsafe symbolic-link session lock' 2
[[ "$WORKSPACE" = /* && -d "$WORKSPACE" ]] || fail 'workspace must be an existing absolute directory' 2
[[ "$AGENT_COMMAND" = /* ]] || fail 'agent_command must be an absolute path' 2
wait_for_file "$AGENT_COMMAND" || fail 'agent_command is unavailable after bounded retry' 5
[[ -f "$ENV_FILE" ]] || fail 'DeepSeek environment file is missing' 6
wait_for_file "$BASE_CLAUDE" || fail 'Claude executable is unavailable after bounded retry' 5
validate_bootstrap || exit $?
validate_client_runtime
validate_authority_runtime
mkdir -p -- "$STATE_ROOT"
if ! mkdir -- "$LOCK_DIR" 2>/dev/null; then
  [[ ! -L "$LOCK_DIR" ]] || fail 'unsafe symbolic-link session lock' 2
  existing_pid="$(lock_metadata_pid "$LOCK_DIR")"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then fail "this client already has an active Claude session (pid $existing_pid)" 10; fi
  fail 'stale session lock detected; run the repair entry for explicit cleanup' 11
fi
trap remove_own_lock EXIT INT TERM
write_metadata || fail 'could not write session metadata' 12
cd "$WORKSPACE" || fail 'could not enter workspace' 2
printf 'Current client: %s\nCurrent workspace: %s\nOps Brain bootstrap verified; starting Claude Code through claude-deepseek...\n' "$CLIENT_ID" "$WORKSPACE"
if [[ -f "$SHARED_CAPABILITY_MANIFEST" ]]; then
  run_agent_with_shared_capability_env
else
  "$AGENT_COMMAND" --setting-sources project --plugin-dir "$AUTHORITY_PLUGIN" --agent "$PRIMARY_AGENT" --append-system-prompt "$(<"$BOOTSTRAP_FILE")"
fi
exit_code=$?
printf 'Claude Code exited with code: %s\n' "$exit_code"
exit "$exit_code"
