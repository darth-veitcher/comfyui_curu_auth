# Epic: A browser tab recovers from a lost session

<!-- Write this epic to section 7 of docs/WRITING.md (ASD-STE100). -->

## Status
Planning  — started 2026-11-02

## Why now
The session store is in memory, so each ComfyUI restart removes all sessions. curu restarts ComfyUI often. An open ComfyUI tab then continues to poll `/api/jobs` and to open `/ws` with no valid session.

The gate rejects each of these requests with HTTP 401 and writes one "authentication failure" line. The tab never shows the login page. The user sees a broken page, and fail2ban or crowdsec can ban the address of the user.

ADR-005 stopped the lockout: the gate expires the stale cookie, so the rate limiter does not count the requests. But the tab still sends the requests, and the log still fills. This epic makes the tab recover by itself.

## Dependencies
_Other epics that must reach Done before this one starts. Add one bullet for
each dependency: `- <slug> — <optional criterion>`. Leave the list empty if
there are none. `beacon doctor` gates on one slug in each bullet. It reads a
bullet that is a sentence as prose. Thus you can say what is *not* a
dependency, and no false gate occurs._

This epic has no dependency. The browser test of the rauthy tier already exists, so the Playwright tooling is available.

## Specs
_SpecKit specs that contribute to this epic. `beacon specify --epic <slug>`
links them. Otherwise, add each one by hand._

<!-- - specs/001-example/   — short description -->

- specs/005-session-loss-reload/ — An open tab goes to the login page when its session is lost

## ADRs
_Decisions that cross the specs of this epic. To create or edit an epic is
a BEACON DESIGN-phase activity. A choice that spans specs belongs here, not
in one spec.md. Examples: "OAuth or our own auth", "which database", "build
or buy". Write each ADR in `project-management/ADRs/` (MADR format), and
link it below. Until the ADR exists, write the decision as a sentence.
`beacon doctor` reads a sentence as a pending decision, not as a broken
link._

- [ADR-004](../../ADRs/ADR-004-only-offered-credentials-count-as-attempts.md) — only an offered credential counts as an attempt.
- [ADR-005](../../ADRs/ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md) — the gate expires a stale cookie; this epic builds on that.
- [ADR-009](../../ADRs/ADR-009-a-module-in-the-comfyui-page-acts-on-a-gate-rejection.md) — a module in the ComfyUI page sends the tab to the login page on a gate rejection.

## Success criteria
- After a ComfyUI restart, an open tab shows the login page within 5 seconds.
- After the tab shows the login page, the tab causes 0 more "authentication failure" lines.
- A tab with a valid session goes to the login page 0 times.
- The responses to programs that send a Bearer header have the same status and body as before.

## Non-goals
- The epic does not keep sessions across a restart.
- The epic does not change the format of the "authentication failure" log line.
- The epic does not change the rate limiter or the rules of ADR-004.
- The epic does not add roles or separate accounts.

## Notes
ComfyUI is one page at `/`. After a login, the gate sends the browser to `/`, so the user returns to the same page.
