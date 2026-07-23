# Problem Statement

<!--
BEACON SEED phase deliverable. Update this as requirements evolve — it is a living document.
Record the date and reason whenever you change it.
-->

## Core Problem

> One sentence: what specific problem does this project solve?

ComfyUI ships with zero built-in authentication — anyone who can reach its HTTP port has full API access, including workflow execution and the `/ws` websocket — so this node puts a bearer-token gate in front of the whole backend with no external dependencies.

## Target User

**Who:** Self-hosted ComfyUI operators — people running it on a home GPU box, a rented GPU pod, or an internal server.
**Context:** The moment they expose ComfyUI's port beyond `127.0.0.1` — reverse proxy, port-forward, cloud rental — and realize there's no login screen at all.
**Current pain:** They either leave it wide open (ComfyUI instances get scanned/hit by botnets), or hand-roll reverse-proxy basic-auth, which doesn't cover the `/ws` handshake the UI depends on — breaking live progress silently.

## Success Criteria

How will we know this is working? Make these measurable.

- [ ] Install + restart is the entire setup — no config file, no account creation, credential prints to console
- [ ] Every route including the `/ws` websocket handshake is covered by the gate — no silent bypass
- [ ] Repeated bad credentials get exponential backoff on both the login form and Bearer-header paths, without affecting already-authenticated sessions

## Non-Goals

Explicitly naming what we are **not** solving prevents scope creep.

1. NOT multi-user — one shared credential, no accounts/roles
2. NOT a TLS replacement — adds authentication only, doesn't encrypt traffic
3. NOT external identity today — OIDC/OAuth and passkey (WebAuthn) support are future additions (see Roadmap vision), not permanently ruled out

## Why This Matters

ComfyUI has no first-party auth, so exposing it beyond localhost is one port-scan away from a stranger running arbitrary workflows on your GPU. This closes that gap with a five-minute install and no ongoing maintenance.

## Constraints

Must patch ComfyUI's already-running `aiohttp` app at import time (no fork, no `server.py` edits); no network egress to verify credentials.

---

_Created:_ 2026-07-23
_Last updated:_ 2026-07-23 — BEACON SEED phase: filled in from existing README/codebase
_Status:_ Living document — update when requirements evolve
