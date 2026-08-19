# ADR-001: Cheat primary authority and client-owned state

Status: accepted by Owner

## Decision

- XBuilderLAB/cheat-on-content is the PRIMARY operational core and final judgment framework.
- Each client workspace is the canonical owner of Cheat business state.
- The global Cheat installation is read-only implementation.
- social-account-doctor is a subordinate evidence/diagnosis provider.
- Missing or invalid client state fails explicitly.

## Runtime mechanism

Standard client sessions use Claude Code project-only setting sources, a Manager-owned plugin, and an explicitly selected root Core agent. This removes user-global Skill competition. Doctor is exposed only as an internal subagent whose result returns to Core with `final_authority: false`.

## Rejected alternatives

- Prompt-only “prefer Cheat” rules: do not prevent global Skill competition.
- A second shared client-state engine: duplicates Cheat state and creates competing truth sources.
- Keyword-only dispatch: replaces AI reasoning with a brittle intent bot.
- Deleting Doctor: loses valuable evidence capability rather than correcting authority.
- Silent fallback on missing state: presents a stateless assistant as a working Ops Brain.
