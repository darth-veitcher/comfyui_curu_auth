# Roadmap — Strategy

**Project:** comfyui_curu_auth
**Last reviewed:** 2026-11-01

---

> This file is **strategy** (quarter-scope). It is **not** the live status tracker
> for active work — that's discovered from git branches and `specs/` by
> `beacon bullet list`. It is **not** the per-initiative artifact — those live as
> per-file epics under [`epics/`](./epics/).
>
> What goes here: vision, quarter priorities, sequencing, dependency notes, and
> the broader product context the in-flight epics ladder up to.

---

## Vision

> One paragraph: what problem class are we addressing this year? What does
> "winning" look like at year-end?

By year-end, this is the default way to put a password on ComfyUI for self-hosted and rented-GPU users. It installs with no configuration, covers each route with the websocket, and works with fail2ban and crowdsec. Next, more people can log in: OIDC for teams with an identity provider, and passkeys for a passwordless login. Both are options next to the credential, which stays simple for one person at home.

---

## This quarter

The two-to-five concrete initiatives you've committed to delivering this quarter.
Each is materialised as an epic file under [`epics/`](./epics/) with its own
success criteria, owned specs, and ADRs.

- **OIDC with real providers** — `epics/oidc-auth.md` — the OIDC login works with rauthy and Authentik (spec 003). Programs can send OIDC access tokens (spec 004).
- **Passkeys** — `epics/passkey-auth.md` — a passwordless login. Not started.
- **Browser end-to-end tests** — `epics/browser-e2e.md` — started: the rauthy tier of spec 003 adds the first Playwright test.

For the live rollup (specs per epic, % tasks complete, last-commit age):

```
beacon epic list --detailed
```

---

## Sequencing and dependencies

- Spec 004 (access tokens on the Bearer path) needs the issuer and key code of spec 003, so it starts after spec 003 merges.
- Passkeys are independent of OIDC.

---

## Out of scope this quarter

What you're explicitly **not** doing, with one-line rationale each. Prevents
opportunistic scope creep and gives a paper trail when priorities shift.

- Roles or separate accounts — the gate stays one boundary.
- More than one OIDC provider at a time.

---

## Where things live

| Layer | Where | What's in it |
|---|---|---|
| Strategy | this file | vision, quarter priorities (slow, manual) |
| Epic / initiative | `epics/<slug>.md` | scope, ADRs, owned specs (weeks-scope) |
| Feature / spec | `specs/<NNN-slug>/` | SpecKit-generated user scenarios, plan, tasks |
| Active work | git branches + `specs/<NNN-slug>/tasks.md` + `.beacon/bullets.toml` | discovered live by `beacon bullet list` |
| Architectural decisions | `project-management/ADRs/` | epic-level MADRs, linked from the relevant epic |

---

*Last reviewed: 2026-07-23 — refresh this date every quarter. `beacon doctor`
will warn if it goes stale (>90 days).*
