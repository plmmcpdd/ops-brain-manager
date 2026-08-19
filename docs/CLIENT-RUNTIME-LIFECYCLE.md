# Client runtime lifecycle

## States

- `NOT_INITIALIZED`: no Cheat runtime artifact exists.
- `READY`: state is valid schema 1.4 and all required client-owned artifacts are present.
- `PARTIAL`: Cheat artifacts exist but the canonical state is absent.
- `INVALID`: state JSON/fields or ownership safety is invalid.
- `NEEDS_REPAIR`: valid state exists but generated files, directories, hooks, or migration readiness is incomplete.

## Operator flow

Create and inspect:

```bash
python3 ops_brain.py create --name "Client" --workspace-root /home/rong/projects/content-ops-clients
python3 ops_brain.py runtime status --client client
```

Initialize only after collecting explicit Cheat onboarding choices:

```bash
python3 ops_brain.py runtime initialize --client client \
  --content-form short-text \
  --cadence-days 2 \
  --data-collection manual \
  --pool-status none \
  --benchmark-status pending \
  --hooks yes
```

The command copies upstream templates into the client workspace, writes client state, merges Cheat hooks, and preserves unrelated business files. It refuses partial, invalid, and conflicting layouts. Repeating it on a `READY` runtime is a no-op.

Inspect or repair:

```bash
python3 ops_brain.py runtime inventory
python3 ops_brain.py runtime status --client client
python3 ops_brain.py runtime repair --client client
```

Repair only restores missing generated artifacts when a safe, current `.cheat-state.json` already exists. It never reconstructs state, overwrites existing artifacts, or performs schema migration. Invalid JSON and old schemas require operator review and the upstream Cheat migration protocol.

`open`, `resolve-launch`, and the Agent launcher all fail closed unless status is `READY`.
