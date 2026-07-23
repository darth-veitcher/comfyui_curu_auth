# Epic: Passwordless WebAuthn/passkey login

## Status
Planning  — started 2026-07-23

## Why now
The Roadmap vision names passkeys/WebAuthn as a passwordless,
phishing-resistant option alongside OIDC. It's sequenced last: more moving
parts than OIDC (relying-party config, credential storage) and lower
urgency per the problem statement's non-goals, and it can reuse whatever
opt-in-auth-method plumbing the `oidc-auth` epic establishes.

## Dependencies
_Other epics that must reach Done before this one starts. Add a bullet per
dependency: `- <slug> — <optional criterion>`. Leave empty if none._

- browser-e2e — a WebAuthn ceremony can't be exercised through
  `local-test-harness`'s HTTP/WS-only harness (adversarial engineering
  review, 2026-07-23, corrected this from an earlier, infeasible
  dependency on `local-test-harness` directly — that harness deliberately
  has no browser tooling). This epic's *auth logic* itself can still be
  built and unit-tested hermetically in parallel with `browser-e2e`; only
  end-to-end verification is gated on it.

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

- [ADR-003](../../ADRs/ADR-003-gate-public-paths-generalization.md) — the shared mechanism this epic's own WebAuthn ceremony routes will register through

## Success criteria
- Operator can register a passkey and log in with it (WebAuthn ceremony)
  as an alternative to the default credential — verified end-to-end via
  the `browser-e2e` epic's browser-driven harness, not the HTTP/WS-only
  `local-test-harness`
- Default zero-config credential path is unaffected when no passkey is
  registered
- Passkey/relying-party setup is documented clearly enough for a
  self-hosted operator to configure without an external service

## Non-goals
- Not a replacement for the default credential — additive only
- Not syncing passkeys across devices/relying parties beyond what the
  browser's own platform authenticator already provides
- Not building a recovery flow beyond what already exists — the shared
  credential remains the fallback if a passkey is lost

## Notes
Not yet built — soft-depends on patterns from `oidc-auth` (opt-in
auth-method plumbing) even though there's no hard blocking dependency.
