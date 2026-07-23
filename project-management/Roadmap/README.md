# Roadmap — Strategy

**Project:** comfyui_curu_auth
**Last reviewed:** 2026-07-23

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

By year-end, this is the default answer to "how do I put a password on ComfyUI" for self-hosted and rented-GPU users — zero-config bearer-token install, every route covered including websockets, fail2ban/crowdsec ready for public-IP deployments. From there, we expand *who* gets to authenticate: OIDC/OAuth for teams with an existing identity provider, and passkeys/WebAuthn for a passwordless, phishing-resistant flow — added as options alongside the credential model, not replacing its zero-config simplicity for solo/home users.

---

## This quarter

The two-to-five concrete initiatives you've committed to delivering this quarter.
Each is materialised as an epic file under [`epics/`](./epics/) with its own
success criteria, owned specs, and ADRs.

- **[Initiative A]** — `epics/<slug>.md` — one-line outcome
- **[Initiative B]** — `epics/<slug>.md` — one-line outcome
- **[Initiative C]** — `epics/<slug>.md` — one-line outcome

For the live rollup (specs per epic, % tasks complete, last-commit age):

```
beacon epic list --detailed
```

---

## Sequencing and dependencies

- Initiative A blocks B (B depends on the auth foundation A delivers).
- Initiative C is independent and can ship in parallel.
- [...]

---

## Out of scope this quarter

What you're explicitly **not** doing, with one-line rationale each. Prevents
opportunistic scope creep and gives a paper trail when priorities shift.

- [Feature X] — deferred to Q3 because [reason]
- [Integration Y] — out of scope; team Z owns it

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
