# Data model: An open tab goes to the login page when its session is lost

**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)

The feature stores no data on the server. It has one mark on the server and one state machine in the tab.

## Gate rejection mark

| Field | Value | Rule |
|---|---|---|
| Header name | `X-Curu-Auth` | The gate sets it only in its middleware. |
| Header value | `login-required` | A fixed string. It holds no credential or token (FR-008). |
| Responses | The HTTP 401 and the HTTP 429 of the middleware | Only these two. The status and the body do not change (FR-007). |

The HTTP 302 to the login page does not need the mark. `fetch` follows it, and the tab reads the final URL (research R3).

## Tab state

The module keeps three values for each page load.

| Value | Type | Where | Meaning |
|---|---|---|---|
| `leaving` | boolean | memory | The module called `location.assign`. Each later trigger does nothing. |
| `lastProbe` | time in ms | memory | The time of the last `/ws` probe. The next probe waits 2 seconds. |
| `curu-auth:left-at` | time in ms | `sessionStorage` | The time of the last move to the login page. The next move waits 5 seconds (FR-010). |

## State transitions

```text
                 fetch answer with mark,
                 or redirect to the login page
  ┌─────────┐ ─────────────────────────────────────────────┐
  │ WATCH   │                                               ▼
  │         │  socket closes      ┌─────────┐  mark   ┌──────────┐
  │         │ ──────────────────▶ │ PROBE   │ ──────▶ │ LEAVE    │
  │         │  before it opens,   │         │         │ location │
  │         │  last probe > 2 s   └─────────┘         │ .assign  │
  │         │ ◀────────────────── no mark, or         └──────────┘
  └─────────┘                     network error
```

- **WATCH**: The default state. The page works as normal.
- **PROBE**: One `GET` of the URL of the module is in flight.
- **LEAVE**: The final state. If `curu-auth:left-at` is less than 5 seconds old, the module stays in WATCH and does not move.
