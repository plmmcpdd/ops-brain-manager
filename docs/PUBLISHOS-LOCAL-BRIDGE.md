# PublishOS Local Bridge

## Scope and architecture

The bridge is a local, read-only pull path: PublishOS Performance API → Ops Brain Manager → a customer's validated `.cheat-cache/publishos/` JSON and factual `videos/<contentRef>/report.md`. It does not call TikTok, change predictions or rubrics, remove `pending_retros`, run Cheat, make operating conclusions, or push data back to PublishOS.

The Registry remains version 1. A client may optionally contain `integrations.publishos = {"enabled": true, "client_id": "..."}`. Tokens, host addresses, and server information are never saved there.

## Configuration and token

Put a local, ignored profile file at `.ops-brain/integrations/publishos.<profile>.json`; start from `examples/publishos.profile.example.json`. `base_url` must be an absolute URL without query or fragment. Production requires HTTPS and TLS verification. The profile can be selected with `--profile` or `OPS_BRAIN_PUBLISHOS_PROFILE`; base URL, timeout, and TLS can be overridden by the corresponding `OPS_BRAIN_PUBLISHOS_*` environment variables.

The token is read from `OPS_BRAIN_PUBLISHOS_TOKEN`, then `.ops-brain/secrets/publishos.<profile>.token`. It is never accepted as a CLI argument, emitted, cached, reported, or quarantined. On POSIX, a secret file readable by group or others is rejected.

## Commands

```bash
python3 ops_brain.py publishos link --client customer-a --publishos-client-id fictional-client-id
python3 ops_brain.py publishos status --profile development
python3 ops_brain.py publishos sync --client customer-a --content-ref 2026-01-01_example --profile development
python3 ops_brain.py publishos sync --all --due --dry-run --profile development --json
python3 ops_brain.py publishos unlink --client customer-a
```

`link` and `unlink` are local Registry writes only. A PublishOS ID cannot be linked to two active customers. `sync` accepts `--client` or `--all`; with no explicit content ref it reads `pending_retros`. `--due` checks `Published at:` in the matching prediction and the configured window. Dry runs never read a token, send HTTP, write cache/report/quarantine, or mutate state.

## Data safety

Only an allow-listed, schema-validated response is stored. A client or content identity mismatch fails closed. Cache writes use same-directory temporary files, fsync, and replacement. Repeated identical payloads return `no_change` without rewriting `latest.json`; changed payloads retain an immutable timestamp/hash snapshot. Decreasing metrics are preserved and flagged for manual review.

Generated reports contain managed markers plus a manual-comments marker. Existing reports without all markers are treated as conflicts and are not overwritten. Unknown API fields are ignored and never rendered. Failures produce a redacted metadata-only record under `.ops-brain/quarantine/publishos/`; all-customer sync continues after an individual failure.

## Exit codes and JSON

Exit code `0` means success, no change, not due, or no pending content. `1` means partial failures (with quarantine). `2` means invalid configuration, Registry, token, or command input. `--json` writes one ASCII JSON object to stdout; diagnostics are reserved for stderr.

## Migration and current limits

Moving servers only requires changing the local profile configuration; no customer Registry migration is needed. The bridge intentionally has no deployment, background service, retry queue, remote write API, automatic retrospective, or Phase 2B-C analysis capabilities.
