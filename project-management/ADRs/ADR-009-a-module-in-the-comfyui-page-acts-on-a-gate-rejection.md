# ADR-009: A module in the ComfyUI page sends the tab to the login page on a gate rejection

## Status

Accepted

_Date:_ 2026-11-02
_Deciders:_ James Veitch (with Claude Code)

It adds to [ADR-005](ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md). It replaces no ADR.

---

## Context

- The session store is in memory. Each ComfyUI restart removes all sessions, and curu restarts ComfyUI often.
- ADR-005 makes the gate expire a stale cookie on the first rejected request. This stopped the lockout, but not the requests.
- An open ComfyUI tab polls `/api/jobs`, and it opens `/ws` again each 300 ms after a close. These requests do not ask for HTML.
- The gate sends a redirect to the login page only to a request that asks for HTML. Each other request gets HTTP 401 and writes one "authentication failure" line.
- So after a restart, the tab shows a broken page. The log gets about three lines each second until the user reloads the tab.
- Until this ADR, the node had no code in the page (`WEB_DIRECTORY = None`).
- A browser does not show the status of a failed websocket handshake to the page.

## Decision

The node ships one ES module to the ComfyUI page. The module sends the tab to the login page when the gate rejects a request of the tab.

- The gate adds `X-Curu-Auth: login-required` to each HTTP 401 and HTTP 429 of its middleware. The status, the body and the log line do not change.
- `__init__.py` sets `WEB_DIRECTORY = "./web"`. ComfyUI serves `web/session_loss.js` and imports it into the page.
- The module wraps `window.fetch`. An answer with the mark, or a redirect to the login page, sends the tab to the login page.
- The module wraps `window.WebSocket`. When a socket closes before it opens, the module sends one probe to the URL of the module. A probe answer with the mark sends the tab to the login page.
- A network error never sends the tab to the login page.
- The module sends the tab to the login page no more than once in 5 seconds.

## Consequences

- An open tab recovers by itself after a restart. The log gets a few lines for each session loss, not three each second.
- The node now has code in the page. A future ComfyUI frontend can break the wrapper of `fetch` or `WebSocket`. The `system` test against the real frontend finds such a break.
- If the module does not load, the tab behaves as before this ADR. The gate is not affected.
- Programs see one more header on a rejection. They can ignore it.
- The repository gets a `browser` test tier that needs Chromium.

## Considered Alternatives

- **Keep sessions across a restart, for example in a file.** Rejected: a file of session tokens is a secret on disk. It also does not help when a session is not valid for another reason.
- **Put a `<script>` tag into the HTML of `/`.** Rejected: the gate must then change an answer of ComfyUI, and it couples the gate to the HTML of each ComfyUI version.
- **Use the `api` object of the ComfyUI frontend.** Rejected: it is an internal module, and its path and events change between versions.
- **Use `WWW-Authenticate` as the mark.** Rejected: it is for HTTP 401 only, so it does not cover HTTP 429.
- **Add a session route for the probe.** Rejected: a new route is new attack surface, and the URL of the module does the same job.

## Links

- [specs/005-session-loss-reload/spec.md](../../specs/005-session-loss-reload/spec.md)
- [specs/005-session-loss-reload/research.md](../../specs/005-session-loss-reload/research.md)
- [Epic browser-session](../Roadmap/epics/archive/browser-session.md)
