#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHER="$ROOT/launcher/launch_ops_agent.sh"
TMP="$(mktemp -d)"
TEST_HOME="$TMP/home"
mkdir -p "$TEST_HOME/.config/claude-deepseek" "$TEST_HOME/bin"
mkdir -p "$TEST_HOME/.claude/skills/social-account-doctor" "$TEST_HOME/.local/bin"
: > "$TEST_HOME/.config/claude-deepseek/env"
printf 'TIKHUB_API_KEY=configured\n' > "$TEST_HOME/.claude/skills/social-account-doctor/.env"
printf '{"capabilities":[{"install_location":"%s","configuration_file":".env"}]}\n' "$TEST_HOME/.claude/skills/social-account-doctor" > "$TEST_HOME/capabilities.json"
export OPS_BRAIN_SHARED_CAPABILITY_MANIFEST="$TEST_HOME/capabilities.json"
printf '#!/usr/bin/env bash\nexit 0\n' > "$TEST_HOME/.local/bin/tikhub"
chmod +x "$TEST_HOME/.local/bin/tikhub"
printf '#!/usr/bin/env bash\nexit 0\n' > "$TEST_HOME/bin/claude"
chmod +x "$TEST_HOME/bin/claude"
trap 'rm -rf "$TMP"' EXIT
WORK_A="$TMP/work-a"; WORK_B="$TMP/work-b"; STATE="$TMP/state"
mkdir -p "$WORK_A" "$WORK_B"
FAKE="$TMP/fake-agent"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
if [[ -n "${OPS_BRAIN_METADATA_COPY:-}" ]]; then cp -- "${OPS_BRAIN_AGENT_STATE_ROOT}/${OPS_BRAIN_EXPECTED_CLIENT_ID}.lock/metadata.json" "$OPS_BRAIN_METADATA_COPY"; fi
pwd > "${OPS_BRAIN_FAKE_PWD:?}"
printf '%s\n' "${TIKHUB_API_KEY:-missing}" > "${OPS_BRAIN_FAKE_PWD}.env"
command -v tikhub > "${OPS_BRAIN_FAKE_PWD}.tikhub"
printf '%s\n' "$@" > "${OPS_BRAIN_FAKE_PWD}.argv"
sleep "${OPS_BRAIN_FAKE_SLEEP:-0}"
EOF
chmod +x "$FAKE"

make_bootstrap() {
  local client_id="$1" workspace="$2" path
  path="$TMP/projections/$client_id/.ops-launch/initial_prompt.txt"
  mkdir -p "$(dirname "$path")"
  printf 'OPS_BRAIN_BOOTSTRAP v1\nclient_id: %s\ndisplay_name: 测试客户\nworkspace: %s\nrole: Ops Brain / 运营大脑\nworkspace_type: 客户级长期运营工作区，不是普通代码仓库会话。\nstate_entry: 先读取并理解当前客户工作区中的 Cheat / 客户状态入口；不要扫描无关磁盘。\nboundary: 未收到用户明确任务前，不得自行执行生产动作。\nboundary: 不得修改共享 Cheat / Shared Runtime；客户数据、客户状态和共享能力必须保持边界。\ncapabilities: 仅按当前已启用的 shared capabilities 使用能力；不得把共享能力配置复制进客户目录。\n' "$client_id" "$workspace" > "$path"
  printf '%s\n' "$path"
}

run_agent() {
  local client_id="$1" pwd_file="$2" bootstrap
  bootstrap="$(make_bootstrap "$client_id" "$WORK_A")"
  HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$pwd_file" "$LAUNCHER" "$client_id" "$WORK_A" "$FAKE" "$bootstrap"
  [[ "$(<"$pwd_file")" == "$WORK_A" ]]
  [[ "$(<"$pwd_file.env")" == configured ]]
  [[ "$(<"$pwd_file.tikhub")" == "$TEST_HOME/.local/bin/tikhub" ]]
  grep -Fx -- '--append-system-prompt' "$pwd_file.argv"
  grep -Fx -- 'OPS_BRAIN_BOOTSTRAP v1' "$pwd_file.argv"
  grep -Fx -- "client_id: $client_id" "$pwd_file.argv"
  grep -Fx -- 'role: Ops Brain / 运营大脑' "$pwd_file.argv"
  [[ ! -e "$STATE/$client_id.lock" ]]
}

for client_id in ascii-client client_01 小红书一号测试客户 美国移民-01; do
  run_agent "$client_id" "$TMP/$client_id.pwd"
done

unicode_id='小红书一号测试客户'
unicode_bootstrap="$(make_bootstrap "$unicode_id" "$WORK_A")"
HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/unicode.pwd" OPS_BRAIN_METADATA_COPY="$TMP/unicode-metadata.json" OPS_BRAIN_EXPECTED_CLIENT_ID="$unicode_id" "$LAUNCHER" "$unicode_id" "$WORK_A" "$FAKE" "$unicode_bootstrap"
python3 - "$TMP/unicode-metadata.json" "$unicode_id" "$WORK_A" <<'PY'
import json, sys
path, client_id, workspace = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    metadata = json.load(handle)
assert metadata["client_id"] == client_id
assert metadata["workspace"] == workspace
PY
[[ ! -e "$STATE/$unicode_id.lock" ]]

# Bootstrap failures must never invoke an otherwise-valid agent.
if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/missing.pwd" "$LAUNCHER" missing-bootstrap "$WORK_A" "$FAKE" "$TMP/projections/missing-bootstrap/.ops-launch/initial_prompt.txt"; then exit 1; else [[ $? -eq 20 ]]; fi
[[ ! -e "$TMP/missing.pwd" ]]
mismatch_bootstrap="$(make_bootstrap other-client "$WORK_A")"
if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/mismatch.pwd" "$LAUNCHER" expected-client "$WORK_A" "$FAKE" "$mismatch_bootstrap"; then exit 1; else [[ $? -eq 20 ]]; fi
[[ ! -e "$TMP/mismatch.pwd" ]]
invalid_utf8_bootstrap="$(make_bootstrap invalid-utf8 "$WORK_A")"
printf '\377' >> "$invalid_utf8_bootstrap"
if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/invalid-utf8.pwd" "$LAUNCHER" invalid-utf8 "$WORK_A" "$FAKE" "$invalid_utf8_bootstrap"; then exit 1; else [[ $? -eq 20 ]]; fi
[[ ! -e "$TMP/invalid-utf8.pwd" ]]

client_a_bootstrap="$(make_bootstrap client-a "$WORK_A")"
client_b_bootstrap="$(make_bootstrap client-b "$WORK_B")"
HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/live.pwd" OPS_BRAIN_FAKE_SLEEP=2 "$LAUNCHER" client-a "$WORK_A" "$FAKE" "$client_a_bootstrap" &
PID=$!
sleep 0.2
if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/second.pwd" "$LAUNCHER" client-a "$WORK_A" "$FAKE" "$client_a_bootstrap"; then exit 1; else [[ $? -eq 10 ]]; fi
HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/b.pwd" "$LAUNCHER" client-b "$WORK_B" "$FAKE" "$client_b_bootstrap" &
PID_B=$!
wait "$PID" "$PID_B"

mkdir -p "$STATE/client-stale.lock" "$STATE/$unicode_id.lock"
printf '{"client_id":"client-stale","wrapper_pid":999999}\n' > "$STATE/client-stale.lock/metadata.json"
printf '{"client_id":"%s","wrapper_pid":999999}\n' "$unicode_id" > "$STATE/$unicode_id.lock/metadata.json"
stale_bootstrap="$(make_bootstrap client-stale "$WORK_A")"
if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/stale.pwd" "$LAUNCHER" client-stale "$WORK_A" "$FAKE" "$stale_bootstrap"; then exit 1; else [[ $? -eq 11 ]]; fi
[[ -d "$STATE/client-stale.lock" ]]
diagnosis="$(HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" "$LAUNCHER" --diagnose "$FAKE")"
grep -F "lock=$unicode_id status=stale pid=999999" <<<"$diagnosis"
HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" "$LAUNCHER" --clear-stale "$unicode_id"
[[ ! -e "$STATE/$unicode_id.lock" ]]
[[ -d "$STATE/client-stale.lock" ]]

assert_invalid() {
  local value="$1"
  if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/invalid.pwd" "$LAUNCHER" "$value" "$WORK_A" "$FAKE" /missing; then
    printf 'unsafe client_id accepted: %q\n' "$value" >&2
    exit 1
  else
    [[ $? -eq 2 ]]
  fi
}
for value in '' '.' '..' '../escape' 'a/b' 'a\b' $'a\nb' $'a\rb' $'a\x01b' '-leading' 'trailing-' '_leading' 'trailing_' 'con' 'NUL'; do assert_invalid "$value"; done

OUTSIDE="$TMP/outside"
mkdir "$OUTSIDE"
ln -s "$OUTSIDE" "$STATE/symlink-client.lock"
assert_invalid_symlink() {
  if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/symlink.pwd" "$LAUNCHER" symlink-client "$WORK_A" "$FAKE" /missing; then exit 1; else [[ $? -eq 2 ]]; fi
}
assert_invalid_symlink
[[ -L "$STATE/symlink-client.lock" ]]
[[ -z "$(find "$OUTSIDE" -mindepth 1 -print -quit)" ]]

echo 'agent launcher tests passed'
