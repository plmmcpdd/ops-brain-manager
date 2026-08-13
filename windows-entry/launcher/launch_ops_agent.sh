#!/usr/bin/env bash
# Dedicated, non-content-producing launcher for one customer's Claude session.
set -u

STATE_ROOT="${OPS_BRAIN_AGENT_STATE_ROOT:-/home/rong/projects/content-ops-lab/ops-brain-manager/.ops-brain/agent-sessions}"
ENV_FILE="$HOME/.config/claude-deepseek/env"
BASE_CLAUDE="${OPS_BRAIN_BASE_CLAUDE:-/home/rong/.local/bin/claude}"

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

[[ "$#" -eq 3 ]] || fail 'usage: launch_ops_agent.sh client_id workspace agent_command'
CLIENT_ID="$1"; WORKSPACE="$2"; AGENT_COMMAND="$3"
LOCK_DIR="$(lock_path_for_client "$CLIENT_ID")" || fail 'invalid client_id' 2
[[ ! -L "$LOCK_DIR" ]] || fail 'unsafe symbolic-link session lock' 2
[[ "$WORKSPACE" = /* && -d "$WORKSPACE" ]] || fail 'workspace must be an existing absolute directory' 2
[[ "$AGENT_COMMAND" = /* ]] || fail 'agent_command must be an absolute path' 2
wait_for_file "$AGENT_COMMAND" || fail 'agent_command is unavailable after bounded retry' 5
[[ -f "$ENV_FILE" ]] || fail 'DeepSeek environment file is missing' 6
wait_for_file "$BASE_CLAUDE" || fail 'Claude executable is unavailable after bounded retry' 5
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
printf 'Current client: %s\nCurrent workspace: %s\nStarting Claude Code through claude-deepseek...\n' "$CLIENT_ID" "$WORKSPACE"
"$AGENT_COMMAND"
exit_code=$?
printf 'Claude Code exited with code: %s\n' "$exit_code"
exit "$exit_code"
