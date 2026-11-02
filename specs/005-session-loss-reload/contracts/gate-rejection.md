# Contract: The gate rejection

**Spec**: [../spec.md](../spec.md) · **Research**: [../research.md](../research.md) R2

This contract adds one header to two answers of the gate middleware. It changes nothing else.

## The HTTP 401 of the middleware

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json; charset=utf-8
X-Curu-Auth: login-required

{"detail": "missing or invalid credential"}
```

## The HTTP 429 of the middleware

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json; charset=utf-8
Retry-After: 4
X-Curu-Auth: login-required

{"detail": "too many attempts", "retry_after": 4}
```

## Rules

| Id | Rule | Test level |
|---|---|---|
| G1 | Each HTTP 401 of the middleware has `X-Curu-Auth: login-required`. | default |
| G2 | Each HTTP 429 of the middleware has `X-Curu-Auth: login-required`. | default |
| G3 | The status and the body of G1 and G2 are the same as before. | default |
| G4 | An accepted request has no `X-Curu-Auth` header. | default |
| G5 | An HTTP 401 that a handler gives has no `X-Curu-Auth` header from the gate. | default |
| G6 | The HTTP 401 of a refused access token (ADR-008) also has the mark. | default |
| G7 | The HTTP 503 "identity provider unavailable" has no mark. The tab must not leave when the provider is down. | default |
| G8 | The log line of each rejection does not change. | default |
| G9 | The login form (`POST /curu-auth/login`) and the OIDC routes do not change. | default |

## What the mark does not mean

The mark does not say why the gate rejected the request. A tab does not need the reason (research R2). A program can ignore the header.
