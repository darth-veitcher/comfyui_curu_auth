# Research: An open tab goes to the login page when its session is lost

**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)

Each section gives the decision, the reason, and the alternatives that we did not choose.

## R1. Where the code for the tab runs

**Decision**: The node sets `WEB_DIRECTORY = "./web"` and ships one ES module, `web/session_loss.js`.

**Rationale**: ComfyUI serves each file of `WEB_DIRECTORY` at `/extensions/<node folder>/`. The frontend gets the list from `GET /extensions` and imports each file into the page. This is the normal way for a custom node to add code to the page. It needs no build step and no new dependency.

**Alternatives**:

- The gate puts a `<script>` tag into the HTML of `/`. Rejected: the gate must then change the body of a ComfyUI answer. That couples the gate to the HTML of each ComfyUI version.
- The gate sends a `Refresh` header. Rejected: a browser obeys `Refresh` only on a page load, not on a fetch or a websocket.

## R2. How the gate marks its own rejection

**Decision**: The gate adds the header `X-Curu-Auth: login-required` to each HTTP 401 and HTTP 429 that its middleware gives.

**Rationale**: A header does not change the status or the body (FR-007). The value is a fixed string, so it holds no credential or token (FR-008). ComfyUI and other nodes do not send this header, so the tab can tell a gate rejection apart (FR-004, FR-006).

A rejection by the gate always means that the tab has no valid session. A valid cookie passes the middleware before each rejection branch (`gate.py`, the first check of `gate`). So the tab does not need to know why the gate rejected it.

**Alternatives**:

- `WWW-Authenticate: Bearer realm="comfyui_curu_auth"`. Rejected: RFC 9110 defines it for HTTP 401 only, so it does not cover HTTP 429 (FR-003). A program can also read it as a request to change its Bearer header.
- A field in the JSON body. Rejected: it changes the body that programs see (FR-007, SC-006).
- The text `missing or invalid credential` in the body. Rejected: another node can give the same text, and a change to the text breaks the tab.

## R3. How the tab sees a gate rejection on a fetch

**Decision**: The module wraps `window.fetch`. When a response has the mark, the module sends the tab to the login page. When a followed redirect ends at the login page, the module does the same.

**Rationale**: The ComfyUI frontend calls the global `fetch` for each API request, also for the `/api/jobs` poll. The wrapper sees each response with no knowledge of the internals of ComfyUI. The gate answers a request that asks for HTML with a redirect to the login page. `fetch` follows that redirect, so `response.url` is the login page.

**Alternatives**:

- Wrap `api.fetchApi` from `/scripts/api.js`. Rejected: this is an internal module of the ComfyUI frontend. Its path and its methods change between versions.

## R4. How the tab sees a gate rejection on `/ws`

**Decision**: The module wraps `window.WebSocket`. When a socket closes before it opens, the module sends one probe request. The probe is `GET` of the URL of the module itself, with `cache: "no-store"`. If the probe answer has the mark, the module sends the tab to the login page.

**Rationale**: A browser does not show the status of a failed websocket handshake to the page. The close event has code 1006 for each failure: a gate rejection, a server that is down, or a network error. The probe tells these causes apart:

| Probe result | Cause | Action |
|---|---|---|
| Answer with the mark | The gate rejects the session | Go to the login page |
| Answer with no mark | The session is valid | Stay |
| Network error | The server cannot be reached | Stay (FR-005) |

The URL of the module is a gated route, it always exists, and it is small. It needs no new route, so it adds no attack surface (article I).

The frontend opens a new socket each 300 ms after a close. The module sends no more than one probe in 2 seconds. So a server that is down causes no more than 15 probes in 30 seconds.

The first socket can open before the module loads, so the wrapper does not see it. Each socket that the frontend opens again after a close is a new `WebSocket`, so the wrapper sees it.

**Alternatives**:

- Listen to the `reconnecting` event of the ComfyUI `api` object. Rejected: it is an internal event of the ComfyUI frontend (see R3).
- Probe a new route, for example `/curu-auth/session`. Rejected: a new route is new attack surface. The URL of the module does the same job.
- Poll a probe each few seconds. Rejected: it causes requests when nothing fails.

## R5. How the tab goes to the login page

**Decision**: The module calls `location.assign("/curu-auth/login")` one time for each page load. It records the time in `sessionStorage`. It does not go again if the last move was less than 5 seconds ago.

**Rationale**: `location.assign` unloads the page. This stops the poll, the socket and each timer of the page (FR-009). The login page does not import the module, so nothing runs there. After a login, the gate sends the browser to `/`, which is the ComfyUI page (spec assumption).

The 5-second limit (FR-010) stops a loop. A loop can occur only if a page loads with a valid session and loses it at once. `sessionStorage` is for one tab only, so the limit of one tab does not affect another tab.

**Alternatives**:

- `location.reload()`. Rejected: the reload asks for HTML, so the gate redirects to the login page. The result is the same, but with one more request and one more log line.
- Read the target from a header. Rejected: the path is fixed (`LOGIN_PATH`), and a fixed path cannot become an open redirect.

## R6. How to test code that runs in a browser

**Decision**: Use two test levels, both with Playwright and Chromium from the `live` group.

1. A `browser` tier in `tests/browser/`. It starts the real gate middleware on aiohttp with a small double of ComfyUI. The double page imports `web/session_loss.js`, polls a route, and opens `/ws`. The test clears the `SessionStore` to cause a session loss.
2. One end-to-end test in the `system` tier. It logs in to the real ComfyUI v0.27.0 frontend in the docker harness, restarts the container, and waits for the login page.

**Rationale**: The `browser` tier runs in seconds and needs no Docker. It covers each branch of the module (R3, R4, R5) and US2. The `system` test proves that the real frontend loads the module and that a real restart works.

The repository has no Node toolchain. A Node test runner adds a toolchain for one small file (article V).

**Alternatives**:

- Add the browser test to the `rauthy` tier. Rejected: that tier needs rauthy, and this feature does not.
- Test the module with Node and `jsdom`. Rejected: a new toolchain, and `jsdom` has no real `WebSocket` failure behaviour.

## R8. The open workflow after the move

**Decision**: Rely on the ComfyUI setting `Comfy.Workflow.Persist`.

**Rationale**: The frontend of ComfyUI v0.27.0 has the setting "Persist workflow state and restore on page (re)load". Its default is on (`defaultValue: true`, frontend 1.16.1 and later). The frontend writes the open workflow to browser storage and reads it at the next page load. So the move to the login page does not lose the workflow.

## R7. Effect on the log and on fail2ban

**Decision**: No change to the log line.

**Rationale**: Between a session loss and the login page, the tab sends some requests. Each one writes one `authentication failure from <IP>` line, as today. After the move, the tab sends nothing. So the number of lines falls from one each 300 ms to a few for each loss (SC-002, SC-003). A rejection with no credential does not count for the rate limiter (ADR-004), so the rate limiter does not change.
