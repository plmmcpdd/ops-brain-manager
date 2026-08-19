# Shared capabilities

Ops Brain clients share capability code through the agent runtime, while reports and assets remain in each client's current workspace.

Shared capabilities are subordinate evidence providers, not operating brains. Standard client sessions disable the Skill system, remove the root `Skill` tool, scope root delegation to `ops-brain-runtime:doctor-evidence`, and load the Manager-owned plugin explicitly. The Doctor Skill root is not added to the session; only its `scripts/` and `references/` implementation surfaces are available to the subordinate adapter. Doctor must return `final_authority: false` to Core. Capability availability never grants state ownership or final decision authority.

The authoritative distribution definition is `shared-capabilities/manifest.json`. The first verified capability is `social-account-doctor`, installed once at `~/.claude/skills/social-account-doctor` from the pinned upstream commit. Do not copy it into customer workspaces. The runtime is upstream code plus the manifest-declared local compatibility patches; it must not be represented as an unmodified upstream build.

Install on a new runtime:

1. Clone the manifest `source` into a trusted tools directory and checkout the exact `pinned_commit`.
2. Apply every `local_patches` entry, in manifest order, from the Ops Brain repository root. For the current capability, apply `0001-doubao-ark-chat-url.patch`, `0002-visual-batch-performance.patch`, `0003-tikhub-failure-policy.patch`, `0004-xhs-app-v2-rest-primary.patch`, then `0005-find-budget-stop-condition.patch`.
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
VIDEO_ANALYSIS_CONCURRENCY=3
VIDEO_ANALYSIS_THINKING=disabled
VIDEO_ANALYSIS_TOKEN_BUDGETS=2000,4000
```

Keep `VIDEO_ANALYSIS_USE_VIDEO_URL=0` for the first provider qualification so video analysis uses the existing JPEG-frame fallback. Audio transcription is a separate protocol integration and remains optional/not configured unless a compatible `/audio/transcriptions` provider is supplied.

For cover sets, invoke `analyze_image.py` once with all paths. The Ops Brain runtime uses concurrency 3, disables Doubao thinking for perception-only work, and uses a measured 2000-token budget with one 4000-token retry. Per-image timing is emitted to stderr without keys or image payloads.

`ops_brain.py doctor` remains Core/Registry health only. `capabilities` reports optional third-party health separately, so provider outages or missing optional visual/audio configuration do not make Ops Brain Core unhealthy.

The Agent launcher starts Claude after `cd "$WORKSPACE"`. Upstream writes completed business outputs to `./reports` and `./assets`; therefore shared code does not imply shared customer output.
The launcher also adds `~/.local/bin` to `PATH` and loads each manifest-declared Skill `.env` into the Claude process through an allowlist. Secrets stay in the runtime configuration and are not copied to the workspace.
It also derives `OPS_BRAIN_VISUAL_CONFIG_STATUS=READY|PARTIAL|MISSING` from presence only. Doctor uses that marker to classify configuration failures without printing values. Environment is captured at process start; after capability configuration changes, close the old Claude session and start a new standard Ops Brain session.

## TikHub failure contract

Xiaohongshu production calls use the stable `tikhub xiaohongshu <action>` adapter and Direct App V2 REST. Configure the runtime, not customer workspaces:

```dotenv
TIKHUB_XHS_TRANSPORT=rest
TIKHUB_REST_BASE_URL=https://api.tikhub.io
TIKHUB_REST_TIMEOUT_SECONDS=45
```

Use `https://api.tikhub.dev` for a verified mainland runtime when appropriate. Both hosts use the existing `TIKHUB_API_KEY`; no second credential is introduced. Implemented actions are `search_notes`, `search_users`, `get_user_posted_notes`, `get_image_note_detail`, `get_video_note_detail`, `get_note_comments`, `get_note_sub_comments`, and `get_user_info`.

For Xiaohongshu, App V1, Web V2, and Web V3 are obsolete production routes and are filtered from CLI discovery. MCP remains available for other platforms and as an optional App V2 diagnostic transport; it is not the Xiaohongshu production primary. A successful REST call does not also call MCP.

MCP platform calls retry the same tool and arguments once after a short backoff. A failure with MCP-session evidence gets one final attempt after session refresh. `can't start new thread` is treated as an upstream transient error and receives only the bounded MCP retry.

Xiaohongshu REST classifies HTTP 401 as `credential_problem` without retry, HTTP 429 as `rate_limited` with one bounded backoff, other 4xx as `request_error`, 5xx/connection/timeouts as `transient` with one bounded retry, and successful HTTP responses with a non-success provider code as `provider_error`. Exhaustion returns `layer=TikHub`, `platform=xiaohongshu`, `transport=rest`, and `status=unavailable`; REST errors never trigger obsolete XHS routes.

After retries are exhausted, TikHub is marked unavailable without changing its API key. Web Search or Jina results may be supplied only as clearly labeled secondary evidence and must never be represented as TikHub or platform-ground-truth data.

Capability diagnostics intentionally separate `XHS App V2 REST` from optional `TikHub MCP`. A degraded MCP transport does not degrade `social-account-doctor` while required XHS REST and dependencies are ready. Optional unconfigured audio is reported as `OPTIONAL_NOT_CONFIGURED`, not as a capability failure.

## Candidate find budget

A plain request for N Xiaohongshu benchmark candidates enters `CANDIDATE_FIND`, not deep research. The Agent makes one primary `search_notes` request and stops immediately when it has N valid candidates. Only an insufficient first result permits one supplementary `search_notes`; two searches are the hard normal limit.

Candidate find performs no user search, account lookup, user-post lookup, detail, comments, or visual analysis. The only exception is an explicit `CANDIDATE_FIND_WITH_INTENT` request, which may fetch top-level comments once for each final candidate after candidate selection. Detail, account research, sub-comments, visual, and video belong to `ENRICH / CRACK` and apply only to items explicitly selected by the Owner.

The Agent-visible and machine-tested contract is installed as `references/find-budget-contract.json`. If two searches yield fewer than N candidates, return the actual count and state that the platform search was insufficient; never make a third search merely to fill the list.
