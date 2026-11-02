# Feature Specification: An open tab goes to the login page when its session is lost

**Feature Branch**: `005-session-loss-reload`

**Created**: 2026-11-02

**Status**: Draft

**Input**: User description: "An open ComfyUI tab whose session is gone goes to the login page by itself. Today the tab keeps polling `/api/jobs` and reconnecting `/ws`, and each request writes an authentication failure line."

**Epic**: [browser-session](../../project-management/Roadmap/epics/archive/browser-session.md)

## Context

The session store is in memory. A ComfyUI restart removes all sessions, but the browser keeps its `curu_auth` cookie. ADR-005 makes the gate expire that cookie on the first rejected request.

An open ComfyUI tab sends background requests. It polls `/api/jobs`, and it opens `/ws` again each 300 ms after the socket closes. These requests do not ask for HTML, so the gate gives HTTP 401 and not a redirect to the login page.

The result is in the log of an operator:

```text
[WARNING] comfyui_curu_auth: authentication failure from 192.168.1.157 (GET /ws)
[WARNING] comfyui_curu_auth: authentication failure from 192.168.1.157 (GET /api/jobs)
```

A session loss ("the loss") is the state where a tab had a valid session and the gate now rejects its session. A gate rejection is an HTTP 401 or HTTP 429 that the gate gives, not ComfyUI or another custom node.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The tab goes to the login page after a restart (Priority: P1)

A user has ComfyUI open in a tab. curu restarts ComfyUI. The tab shows the login page by itself. The user logs in and sees ComfyUI again.

**Why this priority**: This is the value of the feature. It removes the broken page and the log lines.

**Independent Test**: Log in with Chromium, restart the session store, and wait. Measure the time until the tab shows the login page. Count the log lines.

**Acceptance Scenarios**:

1. **Given** a tab with a valid session, **When** the session store loses the session, **Then** the tab shows the login page within 5 seconds.
2. **Given** a tab that polls `/api/jobs`, **When** the gate rejects the poll, **Then** the tab goes to the login page.
3. **Given** an idle tab with only the `/ws` socket, **When** the gate rejects the `/ws` handshake, **Then** the tab goes to the login page.
4. **Given** the tab shows the login page, **When** 60 seconds pass, **Then** the log has no new "authentication failure" line from the tab.
5. **Given** the tab shows the login page, **When** the user logs in, **Then** the tab shows ComfyUI at `/`.
6. **Given** OIDC is on, **When** the session of an OIDC login is lost, **Then** the tab goes to the login page.

---

### User Story 2 - A tab with a valid session stays on its page (Priority: P1)

A user with a valid session works in ComfyUI. The tab never goes to the login page by mistake, also when the server is down for a short time.

**Why this priority**: A false move to the login page interrupts the work of the user. It is worse than the problem that this feature solves.

**Independent Test**: Use ComfyUI in Chromium with a valid session. Stop the server for 30 seconds, and make another node give HTTP 401. Count the moves to the login page.

**Acceptance Scenarios**:

1. **Given** a valid session, **When** ComfyUI or another node gives HTTP 401, **Then** the tab stays on its page.
2. **Given** a valid session, **When** the server cannot be reached, **Then** the tab stays on its page.
3. **Given** the server cannot be reached, **When** the server comes back with the session, **Then** the tab stays on its page.
4. **Given** a valid session, **When** the `/ws` socket closes for a reason other than the gate, **Then** the tab stays on its page.

---

### User Story 3 - Programs and log tools see no change (Priority: P2)

An operator runs curu, comfy-mcp, fail2ban and crowdsec against the gate. Their behaviour does not change.

**Why this priority**: The gate has other clients. The feature is for the browser only.

**Independent Test**: Run the default tests, the `system` tier and the `comfy_mcp` tier. Compare the log lines with the patterns in `contrib/`.

**Acceptance Scenarios**:

1. **Given** a program sends a wrong Bearer header, **When** the gate rejects it, **Then** the status and the body are the same as before.
2. **Given** a program sends the static credential, **When** the gate accepts it, **Then** the program gets the answer of ComfyUI.
3. **Given** a rejected request, **When** the gate writes its log line, **Then** the line matches the patterns in `contrib/`.

---

### Edge Cases

- The gate blocks the address with HTTP 429 after a session loss. The tab goes to the login page, because the login page is public.
- The user has more than one tab open. Each tab goes to the login page by itself.
- The first rejection of the stale cookie counts as one failure (ADR-004, ADR-005). So a login in the first second gets the wait message of the login form.
- The tab has a workflow that the user did not save. ComfyUI keeps the open workflow in browser storage, so the workflow is there after the login.
- The browser does not store the cookie after a login, for example a `Secure` cookie over HTTP. The tab must not loop between ComfyUI and the login page faster than once in 5 seconds.
- The code for the tab does not load, or the ComfyUI frontend is too old for it. The gate stays on, and the tab behaves as it does today.
- A request in the tab gets a gate rejection while the user is on the login page. The login page does not run the code for the tab, so nothing occurs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tab MUST go to the login page when the gate rejects a background request of the tab.
- **FR-002**: The tab MUST go to the login page when the gate rejects the `/ws` handshake of the tab.
- **FR-003**: The tab MUST go to the login page when the gate rejects a request with HTTP 429.
- **FR-004**: The tab MUST NOT go to the login page because of an HTTP 401 from ComfyUI or from another node.
- **FR-005**: The tab MUST NOT go to the login page while the server cannot be reached.
- **FR-006**: The gate MUST mark each of its rejections so that the tab can tell it apart from other rejections.
- **FR-007**: The mark MUST NOT change the status or the body of a rejection.
- **FR-008**: The mark MUST NOT contain a credential, a token or a part of a token.
- **FR-009**: The tab MUST stop all requests to gated routes when it goes to the login page.
- **FR-010**: The tab MUST go to the login page no more than once in 5 seconds.
- **FR-011**: The gate MUST serve the code for the tab only to a request that the gate accepts.
- **FR-012**: An error when the node loads the code for the tab MUST keep the gate on.
- **FR-013**: The node MUST NOT raise from `__init__.py` because of the code for the tab.
- **FR-014**: The gate MUST keep the format of the "authentication failure from <IP>" log line.
- **FR-015**: The static credential path MUST give the same answers as before.
- **FR-016**: The feature MUST work with no new setting.
- **FR-017**: `README.md` or `docs/` MUST say what a user sees when the session is lost.

### Key Entities

- **Session loss**: The state where a tab had a valid session and the gate now rejects its session. A restart or a session that is not valid causes it.
- **Gate rejection**: An HTTP 401 or HTTP 429 that the gate gives. It has a mark that ComfyUI and other nodes do not give.
- **Code for the tab**: The part of the node that runs in the ComfyUI page. It watches for a gate rejection and goes to the login page.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a session loss, the tab shows the login page within 5 seconds, in 10 of 10 test runs.
- **SC-002**: Between a session loss and the login page, the tab causes no more than 10 "authentication failure" lines.
- **SC-003**: After the tab shows the login page, the tab causes 0 "authentication failure" lines in 60 seconds.
- **SC-004**: A tab with a valid session goes to the login page 0 times during a 30-second server stop.
- **SC-005**: A tab with a valid session goes to the login page 0 times after 20 HTTP 401 answers from another node.
- **SC-006**: All default tests, `system` tests and `comfy_mcp` tests pass with no change to their assertions.
- **SC-007**: The patterns in `contrib/` match 100% of the "authentication failure" lines that the tests write.

## Non-goals

- The feature does not keep sessions across a restart.
- The feature does not change the format of the "authentication failure" log line.
- The feature does not change the rate limiter or the rules of ADR-004.
- The feature does not show a message on the login page about the session loss.
- The feature does not return the user to a path other than `/` after a login.
- The feature does not add roles or separate accounts.

## Assumptions

- ComfyUI is one page at `/`, and the gate sends the browser to `/` after a login. So the user returns to the same page.
- ComfyUI lets a custom node add code to its page. Today the node adds none (`WEB_DIRECTORY = None`).
- The browser cannot read the status of a failed `/ws` handshake. The plan finds another way to see a gate rejection on `/ws`.
- ComfyUI keeps the open workflow in browser storage, so a move to the login page does not lose it.
- The Chromium tooling of the rauthy tier can run the browser tests of this feature.
