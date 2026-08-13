#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE_ROOT="$(mktemp -d /tmp/ops-brain-json-contract.XXXXXX)"
trap 'rm -rf "$SMOKE_ROOT"' EXIT
cd "$ROOT"

REGISTRY="$SMOKE_ROOT/registry.json"
CREATE_WS="$SMOKE_ROOT/create-workspace"
ATTACH_WS="$SMOKE_ROOT/attach-workspace"
TEXT_CREATE_WS="$SMOKE_ROOT/text-create-workspace"
TEXT_ATTACH_WS="$SMOKE_ROOT/text-attach-workspace"
mkdir "$ATTACH_WS" "$TEXT_ATTACH_WS"
printf '{"version":1}\n' > "$ATTACH_WS/.cheat-state.json"

CREATE_JSON="$(python3 ops_brain.py --registry "$REGISTRY" create --name 'Smoke Create' --workspace "$CREATE_WS" --json)"
ATTACH_JSON="$(python3 ops_brain.py --registry "$REGISTRY" attach --name 'Smoke Attach' --workspace "$ATTACH_WS" --json)"
SHOW_JSON="$(python3 ops_brain.py --registry "$REGISTRY" show --client 'Smoke Create' --json)"
DOCTOR_JSON="$(python3 ops_brain.py --registry "$REGISTRY" doctor --json)"
RESOLVE_JSON="$(python3 ops_brain.py --registry "$REGISTRY" resolve-launch --client 'Smoke Create' --json)"
set +e
DUPLICATE_JSON="$(python3 ops_brain.py --registry "$REGISTRY" create --name 'Smoke Create' --workspace "$SMOKE_ROOT/duplicate" --json 2>"$SMOKE_ROOT/duplicate.stderr")"
DUPLICATE_EXIT=$?
set -e
TEXT_CREATE="$(python3 ops_brain.py --registry "$REGISTRY" create --name 'Text Create' --workspace "$TEXT_CREATE_WS")"
TEXT_ATTACH="$(python3 ops_brain.py --registry "$REGISTRY" attach --name 'Text Attach' --workspace "$TEXT_ATTACH_WS")"

export CREATE_JSON ATTACH_JSON SHOW_JSON DOCTOR_JSON RESOLVE_JSON DUPLICATE_JSON DUPLICATE_EXIT
export TEXT_CREATE TEXT_ATTACH REGISTRY SMOKE_ROOT
python3 - <<'PY'
import json
import os

names = ("CREATE_JSON", "ATTACH_JSON", "SHOW_JSON", "DOCTOR_JSON", "RESOLVE_JSON", "DUPLICATE_JSON")
payloads = {}
for name in names:
    raw = os.environ[name]
    assert len(raw.splitlines()) == 1, (name, raw)
    payloads[name] = json.loads(raw)
assert payloads["CREATE_JSON"]["ok"] and payloads["CREATE_JSON"]["data"]["origin"] == "created"
assert payloads["ATTACH_JSON"]["ok"] and payloads["ATTACH_JSON"]["data"]["origin"] == "attached"
assert payloads["SHOW_JSON"]["data"] == payloads["CREATE_JSON"]["data"]
assert payloads["DOCTOR_JSON"]["ok"] and payloads["DOCTOR_JSON"]["data"]["clients_checked"] == 2
assert payloads["RESOLVE_JSON"]["ok"] and payloads["RESOLVE_JSON"]["data"]["launch_allowed"]
assert int(os.environ["DUPLICATE_EXIT"]) != 0
assert not payloads["DUPLICATE_JSON"]["ok"] and payloads["DUPLICATE_JSON"]["data"] is None
with open(os.environ["REGISTRY"], encoding="utf-8") as handle:
    registry = json.load(handle)
assert len(registry["clients"]) == 4
assert sum(client["id"] == "smoke-create" for client in registry["clients"]) == 1
assert not os.path.exists(os.path.join(os.environ["SMOKE_ROOT"], "duplicate"))
assert "已创建并登记 Text Create" in os.environ["TEXT_CREATE"]
assert "directory_created=yes; registry_committed=yes" in os.environ["TEXT_CREATE"]
assert "已挂接 Text Attach" in os.environ["TEXT_ATTACH"]
for name in ("CREATE_JSON", "ATTACH_JSON"):
    assert "已创建" not in os.environ[name]
    assert "已挂接" not in os.environ[name]
    assert "directory_created" not in os.environ[name]
print("SMOKE_VALIDATION=PASS")
print("CLIENT_COUNT=4")
print("DUPLICATE_EXIT=" + os.environ["DUPLICATE_EXIT"])
print("CREATE_JSON=" + os.environ["CREATE_JSON"])
print("ATTACH_JSON=" + os.environ["ATTACH_JSON"])
print("DUPLICATE_JSON=" + os.environ["DUPLICATE_JSON"])
print("TEXT_CREATE=" + os.environ["TEXT_CREATE"])
print("TEXT_ATTACH=" + os.environ["TEXT_ATTACH"])
PY
