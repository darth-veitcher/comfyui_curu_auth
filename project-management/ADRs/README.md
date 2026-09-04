# Architectural Decision Records

Decisions that are **hard to reverse**, involve a **real tradeoff**, or would **confuse a future contributor** without context belong here.

## Format

Use [MADR](https://adr.github.io/madr/) — see `ADR-000-template.md`.

## Numbering

`ADR-NNN-short-noun-phrase.md` — sequential, never reuse a number.
Superseded ADRs keep their file; update their status to `Superseded by ADR-###`.

## When to Write an ADR

| Situation | Write ADR? |
|-----------|-----------|
| Choosing a database or storage layer | ✅ Yes |
| Choosing between two library approaches | ✅ Yes |
| Defining an API contract or schema | ✅ Yes |
| Adding a dependency | ✅ If non-trivial |
| Fixing a bug with one obvious fix | ❌ No |
| Renaming a variable | ❌ No |
| Adding a feature that follows existing patterns | ❌ No — spec is enough |

## Index

<!-- Add a row per ADR as you create it: copy ADR-000-template.md to
     ADR-NNN-short-noun-phrase.md, fill it in, then link it here. -->

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [ADR-000](ADR-000-template.md) | Template | — | — |
| [ADR-001](ADR-001-docker-comfyui-test-harness.md) | Docker-based local ComfyUI test harness, adapted from curu's own | Accepted (amended by ADR-004) | 2026-07-23 |
| [ADR-002](ADR-002-oidc-session-sharing-and-test-idp.md) | OIDC session sharing + Authelia as test IdP | Accepted | 2026-07-23 |
| [ADR-003](ADR-003-gate-public-paths-generalization.md) | Generalize `gate.py`'s single-path bypass into a "public paths" set | Accepted | 2026-07-23 |
| [ADR-004](ADR-004-only-offered-credentials-count-as-attempts.md) | Only an *offered* credential counts as an authentication attempt | Accepted | 2026-09-04 |
| [ADR-005](ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md) | Expire a stale session cookie, rather than exempt it from the limiter | Accepted | 2026-09-04 |
