# Ops Brain v1 runtime architecture

## State and authority

`/home/rong/tools/cheat-on-content` is the shared, read-only implementation. Each client workspace owns its own `.cheat-state.json`, rubric, predictions, publication lifecycle, retrospectives, and calibration history. The Manager never maintains a second copy of that business state.

`cheat-on-content` is the PRIMARY operational core and final judgment framework. `social-account-doctor`, TikHub, visual, and audio integrations are auxiliary evidence providers.

## Enforced launch path

```text
Windows projection
  -> Manager resolve-launch (identity + live runtime status)
  -> launch_ops_agent.sh (bootstrap + independent runtime gate)
  -> Claude --setting-sources project
            --plugin-dir runtime/ops-brain-runtime
            --agent ops-brain-runtime:ops-brain-core
  -> Ops Brain Core
       -> client Cheat state and upstream Cheat protocol
       -> optional doctor-evidence subagent
       -> evidence returns to Core
       -> Core final judgment
```

Project-only setting sources remove user-global `cheat-*` and `social-account-doctor` Skills from the client session. This prevents natural-language competition between peers. The explicit root agent makes every user turn enter Core; Doctor exists only as a subordinate Task agent and cannot directly terminate the user operation.

The client runtime gate runs before Claude starts. Missing or invalid state exits explicitly with code 21. Missing authority plugin material exits with code 22.

See [`ADR-001-CORE-AUTHORITY.md`](ADR-001-CORE-AUTHORITY.md) for the frozen decision and [`CLIENT-RUNTIME-LIFECYCLE.md`](CLIENT-RUNTIME-LIFECYCLE.md) for operator commands.
