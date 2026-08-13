# Shared capabilities

Ops Brain clients share capability code through the agent runtime, while reports and assets remain in each client's current workspace.

The authoritative distribution definition is `shared-capabilities/manifest.json`. The first verified capability is `social-account-doctor`, installed once at `~/.claude/skills/social-account-doctor` from the pinned upstream commit. Do not copy it into customer workspaces.

Install on a new runtime:

1. Clone the manifest `source` into a trusted tools directory and checkout the exact `pinned_commit`.
2. Run `bash install_as_skill.sh --target claude`. On an externally managed Python, use a user-scoped package configuration rather than sudo.
3. Put required and optional secrets in the installed Skill's `.env`, mode `0600`. Never store them in this repository, the customer Registry, `runtime.json`, or customer workspaces.
4. Restart Claude Code and run `python3 ops_brain.py capabilities --json`.

`ops_brain.py doctor` remains Core/Registry health only. `capabilities` reports optional third-party health separately, so provider outages or missing optional visual/audio configuration do not make Ops Brain Core unhealthy.

The Agent launcher starts Claude after `cd "$WORKSPACE"`. Upstream writes completed business outputs to `./reports` and `./assets`; therefore shared code does not imply shared customer output.
The launcher also adds `~/.local/bin` to `PATH` and loads each manifest-declared Skill `.env` into the Claude process through an allowlist. Secrets stay in the runtime configuration and are not copied to the workspace.
