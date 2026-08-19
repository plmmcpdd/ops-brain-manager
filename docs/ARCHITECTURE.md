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
            --disable-slash-commands
  -> Ops Brain Core
       -> client Cheat state and upstream Cheat protocol
       -> optional doctor-evidence subagent
       -> evidence returns to Core
       -> Core final judgment
```

Project-only setting sources are not treated as a security boundary: live Claude Code 2.1.217 proved that a root `Skill` tool could still load a hidden global Skill in an interactive session. The launcher therefore disables Skills/slash commands, the root agent has no `Skill` tool, and its `Agent` tool is scoped only to `ops-brain-runtime:doctor-evidence`. The Doctor Skill root is not an additional directory; only its scripts and references are exposed for the subordinate adapter. Cheat protocols remain available by explicit read-only paths rather than Skill invocation.

The client runtime gate runs before Claude starts. Missing or invalid state exits explicitly with code 21. Missing authority plugin material exits with code 22.

See [`ADR-001-CORE-AUTHORITY.md`](ADR-001-CORE-AUTHORITY.md) for the frozen decision and [`CLIENT-RUNTIME-LIFECYCLE.md`](CLIENT-RUNTIME-LIFECYCLE.md) for operator commands.
