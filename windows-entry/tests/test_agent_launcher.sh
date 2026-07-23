#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHER="$ROOT/launcher/launch_ops_agent.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
WORK_A="$TMP/work-a"; WORK_B="$TMP/work-b"; STATE="$TMP/state"
mkdir -p "$WORK_A" "$WORK_B"
FAKE="$TMP/fake-agent"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
pwd > "${OPS_BRAIN_FAKE_PWD:?}"
sleep "${OPS_BRAIN_FAKE_SLEEP:-0}"
EOF
chmod +x "$FAKE"
OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/a.pwd" "$LAUNCHER" client-a "$WORK_A" "$FAKE"
[[ "$(cat "$TMP/a.pwd")" == "$WORK_A" ]]
[[ ! -e "$STATE/client-a.lock" ]]
OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/live.pwd" OPS_BRAIN_FAKE_SLEEP=2 "$LAUNCHER" client-a "$WORK_A" "$FAKE" &
PID=$!
sleep 0.2
if OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/second.pwd" "$LAUNCHER" client-a "$WORK_A" "$FAKE"; then exit 1; else [[ $? -eq 10 ]]; fi
OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/b.pwd" "$LAUNCHER" client-b "$WORK_B" "$FAKE" &
PID_B=$!
wait "$PID" "$PID_B"
mkdir -p "$STATE/client-stale.lock"
printf '{"wrapper_pid":999999}\n' > "$STATE/client-stale.lock/metadata.json"
if OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/stale.pwd" "$LAUNCHER" client-stale "$WORK_A" "$FAKE"; then exit 1; else [[ $? -eq 11 ]]; fi
[[ -d "$STATE/client-stale.lock" ]]
if OPS_BRAIN_AGENT_STATE_ROOT="$STATE" OPS_BRAIN_FAKE_PWD="$TMP/bad.pwd" "$LAUNCHER" '../bad' "$WORK_A" "$FAKE"; then exit 1; fi
echo 'agent launcher tests passed'
