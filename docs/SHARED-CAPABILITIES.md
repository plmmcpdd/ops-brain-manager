# Shared capabilities

Ops Brain clients share capability code through the agent runtime, while reports and assets remain in each client's current workspace.

The authoritative distribution definition is `shared-capabilities/manifest.json`. The first verified capability is `social-account-doctor`, installed once at `~/.claude/skills/social-account-doctor` from the pinned upstream commit. Do not copy it into customer workspaces. The runtime is upstream code plus the manifest-declared local compatibility patches; it must not be represented as an unmodified upstream build.

Install on a new runtime:

1. Clone the manifest `source` into a trusted tools directory and checkout the exact `pinned_commit`.
2. Apply every `local_patches` entry, in manifest order, from the Ops Brain repository root. For the current capability: `git apply /path/to/ops-brain-manager/shared-capabilities/patches/social-account-doctor/0001-doubao-ark-chat-url.patch`.
3. Run `bash install_as_skill.sh --target claude`. On an externally managed Python, use a user-scoped package configuration rather than sudo.
4. Put required and optional secrets in the installed Skill's `.env`, mode `0600`. Never store them in this repository, the customer Registry, `runtime.json`, or customer workspaces.
5. Restart Claude Code and run `python3 ops_brain.py capabilities --json`.

## Doubao Ark visual provider

The pinned upstream assumes either a bare OpenAI-compatible base URL or one ending in `/v1`. Ops Brain's `doubao-ark-chat-url` compatibility patch also treats `/api/v3` as a versioned API root, so `https://ark.cn-beijing.volces.com/api/v3` resolves to `https://ark.cn-beijing.volces.com/api/v3/chat/completions` without an extra `/v1`.

Configure only in the installed Skill's local `.env`:

```dotenv
VIDEO_ANALYSIS_API_KEY=<LOCAL SECRET>
VIDEO_ANALYSIS_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VIDEO_ANALYSIS_MODEL_NAME=<ARK MULTIMODAL MODEL ID>
VIDEO_ANALYSIS_TIMEOUT_SECONDS=600
VIDEO_ANALYSIS_NORMALIZE_IMAGES=1
VIDEO_ANALYSIS_USE_VIDEO_URL=0
```

Keep `VIDEO_ANALYSIS_USE_VIDEO_URL=0` for the first provider qualification so video analysis uses the existing JPEG-frame fallback. Audio transcription is a separate protocol integration and remains optional/not configured unless a compatible `/audio/transcriptions` provider is supplied.

`ops_brain.py doctor` remains Core/Registry health only. `capabilities` reports optional third-party health separately, so provider outages or missing optional visual/audio configuration do not make Ops Brain Core unhealthy.

The Agent launcher starts Claude after `cd "$WORKSPACE"`. Upstream writes completed business outputs to `./reports` and `./assets`; therefore shared code does not imply shared customer output.
The launcher also adds `~/.local/bin` to `PATH` and loads each manifest-declared Skill `.env` into the Claude process through an allowlist. Secrets stay in the runtime configuration and are not copied to the workspace.
