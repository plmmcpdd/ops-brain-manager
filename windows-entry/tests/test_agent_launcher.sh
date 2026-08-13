#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHER="$ROOT/launcher/launch_ops_agent.sh"
TMP="$(mktemp -d)"
TEST_HOME="$TMP/home"
mkdir -p "$TEST_HOME/.config/claude-deepseek" "$TEST_HOME/bin"
: > "$TEST_HOME/.config/claude-deepseek/env"
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
sleep "${OPS_BRAIN_FAKE_SLEEP:-0}"
EOF
chmod +x "$FAKE"

run_agent() {
  local client_id="$1" pwd_file="$2"
  HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$pwd_file" "$LAUNCHER" "$client_id" "$WORK_A" "$FAKE"
  [[ "$(<"$pwd_file")" == "$WORK_A" ]]
  [[ ! -e "$STATE/$client_id.lock" ]]
}

for client_id in ascii-client client_01 小红书一号测试客户 美国移民-01; do
  run_agent "$client_id" "$TMP/$client_id.pwd"
done

unicode_id='小红书一号测试客户'
HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/unicode.pwd" OPS_BRAIN_METADATA_COPY="$TMP/unicode-metadata.json" OPS_BRAIN_EXPECTED_CLIENT_ID="$unicode_id" "$LAUNCHER" "$unicode_id" "$WORK_A" "$FAKE"
python3 - "$TMP/unicode-metadata.json" "$unicode_id" "$WORK_A" <<'PY'
import json, sys
path, client_id, workspace = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    metadata = json.load(handle)
assert metadata["client_id"] == client_id
assert metadata["workspace"] == workspace
PY
[[ ! -e "$STATE/$unicode_id.lock" ]]

HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/live.pwd" OPS_BRAIN_FAKE_SLEEP=2 "$LAUNCHER" client-a "$WORK_A" "$FAKE" &
PID=$!
sleep 0.2
if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/second.pwd" "$LAUNCHER" client-a "$WORK_A" "$FAKE"; then exit 1; else [[ $? -eq 10 ]]; fi
HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/b.pwd" "$LAUNCHER" client-b "$WORK_B" "$FAKE" &
PID_B=$!
wait "$PID" "$PID_B"

mkdir -p "$STATE/client-stale.lock" "$STATE/$unicode_id.lock"
printf '{"client_id":"client-stale","wrapper_pid":999999}\n' > "$STATE/client-stale.lock/metadata.json"
printf '{"client_id":"%s","wrapper_pid":999999}\n' "$unicode_id" > "$STATE/$unicode_id.lock/metadata.json"
if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/stale.pwd" "$LAUNCHER" client-stale "$WORK_A" "$FAKE"; then exit 1; else [[ $? -eq 11 ]]; fi
[[ -d "$STATE/client-stale.lock" ]]
diagnosis="$(HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" "$LAUNCHER" --diagnose "$FAKE")"
grep -F "lock=$unicode_id status=stale pid=999999" <<<"$diagnosis"
HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" "$LAUNCHER" --clear-stale "$unicode_id"
[[ ! -e "$STATE/$unicode_id.lock" ]]
[[ -d "$STATE/client-stale.lock" ]]

assert_invalid() {
  local value="$1"
  if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/invalid.pwd" "$LAUNCHER" "$value" "$WORK_A" "$FAKE"; then
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
  if HOME="$TEST_HOME" OPS_BRAIN_BASE_CLAUDE="$TEST_HOME/bin/claude" OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/symlink.pwd" "$LAUNCHER" symlink-client "$WORK_A" "$FAKE"; then exit 1; else [[ $? -eq 2 ]]; fi
}
assert_invalid_symlink
[[ -L "$STATE/symlink-client.lock" ]]
[[ -z "$(find "$OUTSIDE" -mindepth 1 -print -quit)" ]]

echo 'agent launcher tests passed'
