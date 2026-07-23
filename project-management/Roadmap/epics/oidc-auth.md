# Epic: Optional OIDC/OAuth login path

## Status
Planning  — started 2026-07-23

## Why now
The Roadmap vision names OIDC/OAuth as the next tier of who gets to
authenticate, for operators who already run an identity provider. It
follows `local-test-harness` rather than starting immediately because
verifying a new login path against a real ComfyUI instance — not just
hand-testing — needs that harness to exist first.

## Dependencies
_Other epics that must reach Done before this one starts. Add a bullet per
dependency: `- <slug> — <optional criterion>`. Leave empty if none._

- local-test-harness — a live ComfyUI test target must exist before the
  OIDC login path can be verified end-to-end without hand-testing

## Specs
_SpecKit specs that contribute to this epic. Linked automatically when
`beacon specify --epic <slug>` is used; otherwise add manually._

<!-- - specs/001-example/   — short description -->

## ADRs
_Cross-cutting decisions this epic required. Epic creation/editing is a
BEACON DESIGN-phase activity; the architectural choices that span specs
("OAuth vs own auth", "which database", "build vs buy") belong here,
not in any single spec.md. Create ADRs in `project-management/ADRs/`
(MADR format) and link them below._

- [ADR-001](../../ADRs/ADR-001-docker-comfyui-test-harness.md) — the harness this epic's Authelia extension builds on top of
- [ADR-002](../../ADRs/ADR-002-oidc-session-sharing-and-test-idp.md) — OIDC shares the existing SessionStore/cookie mechanism; Authelia (Lite bundle) is the test IdP

## Success criteria
- Operator can configure an OIDC provider (client id/secret, issuer URL)
  and log in through it, landing on the same session-cookie mechanism the
  default credential path uses
- Default zero-config credential path is completely unaffected when OIDC
  is unconfigured — no new required env vars, no behavior change
- OIDC login attempts get the same failure-logging/rate-limit treatment as
  the existing paths, or an explicit documented reason why not

## Non-goals
- Not a replacement for the default shared-credential model — additive
  only (Constitution Principle I: the zero-dependency default must stay
  intact)
- Not multi-tenant / per-user roles — still gates the whole backend as one
  boundary, just with a second way through the door
- Not building a full identity provider — integrates with one the operator
  already runs

## Notes
**Resolved (2026-07-23, ADR-002)**: both open questions this epic was
blocked on are now decided. OIDC logins share the existing `SessionStore`/
`curu_auth` cookie mechanism (no new session primitive), and Authelia's
**Lite** bundle (file-based users, SQLite, no Postgres/Redis) is the test
IdP extending `local-test-harness`'s `docker-compose.yml` — at the user's
suggestion during epic planning, confirmed against Authelia's own OpenID
Provider certification. Ready to move to `/beacon.specify oidc-auth`.

`project-management/Background/01-final-architecture-document.md` is
still the unfilled template — noted, but no longer a blocker now that the
specific decision that needed it (session sharing) has its own ADR.
