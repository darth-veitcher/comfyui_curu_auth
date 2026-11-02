# Contract: The module in the tab

**Spec**: [../spec.md](../spec.md) · **Research**: [../research.md](../research.md) R1, R3, R4, R5 · **State**: [../data-model.md](../data-model.md)

## Delivery

| Item | Value |
|---|---|
| File | `web/session_loss.js`, one ES module with no imports |
| Served at | `/extensions/<node folder>/session_loss.js` by ComfyUI |
| Wiring | `WEB_DIRECTORY = "./web"` in `__init__.py` |
| Gate | The middleware covers the URL like each other route (FR-011, article II). |

## Behaviour

| Id | Trigger | Result | Test level |
|---|---|---|---|
| T1 | A `fetch` answer has `X-Curu-Auth: login-required`. | The tab goes to `/curu-auth/login`. | browser |
| T2 | A `fetch` follows a redirect to `/curu-auth/login`. | The tab goes to `/curu-auth/login`. | browser |
| T3 | A `fetch` answer is HTTP 401 with no mark. | The tab stays. The page gets the answer as before. | browser |
| T4 | A `fetch` fails with a network error. | The tab stays. The page gets the error as before. | browser |
| T5 | A socket closes before it opens, and the probe answer has the mark. | The tab goes to `/curu-auth/login`. | browser |
| T6 | A socket closes before it opens, and the probe fails with a network error. | The tab stays. | browser |
| T7 | A socket closes before it opens, and the probe answer has no mark. | The tab stays. | browser |
| T8 | A socket closes after it opened. | No probe. The tab stays. | browser |
| T9 | A second socket close occurs less than 2 seconds after a probe. | No second probe. | browser |
| T10 | The last move to the login page was less than 5 seconds ago. | The tab stays (FR-010). | browser |
| T11 | Any trigger after the tab started to leave. | Nothing more occurs. | browser |
| T12 | The real ComfyUI frontend imports the module, and ComfyUI restarts. | The tab goes to `/curu-auth/login` within 5 seconds of the restart. | system |

## Rules for the code

- The wrapper of `fetch` returns the same answer or the same error to the page. It never changes the page's result.
- The probe uses the original `fetch`, not the wrapper.
- The wrapper of `WebSocket` keeps the prototype and the static constants (`OPEN`, `CLOSED` and so on), so the frontend works as before.
- The module catches each of its own errors. An error in the module must not break the ComfyUI page.
- The module writes no token, cookie or header value to the console.
