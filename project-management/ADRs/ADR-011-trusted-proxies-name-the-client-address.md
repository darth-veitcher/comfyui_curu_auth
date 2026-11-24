# ADR-011: A list of trusted proxies decides which X-Forwarded-For entry is the client

## Status

Accepted

_Date:_ 2026-11-24
_Deciders:_ James Veitch (with Claude Code)

---

## Context

The wait after a failure (`RateLimiter`) has one key for each client address.
`gate.client_key` takes the first entry of `X-Forwarded-For`, and else the
peer address. On RunPod this is necessary, because the peer is the address of
the proxy and changes for each request.

The first entry is the entry that the client wrote, if it sent the header. A
proxy appends to the header. So a client that reaches the gate directly, or
through a proxy that keeps the header, chooses its own key.

Behind the Caddy edge of curu-stack on orange-box, the gate saw each browser at
one address. A wrong credential of one browser then made each browser wait. A
browser got HTTP 429 (2026-11-24).

## Decision

An opt-in setting, `COMFYUI_CURU_AUTH_TRUSTED_PROXIES`, gives a list of IP
addresses and CIDR networks. When the list is empty (the default),
`client_key` does not change.

When the list is not empty:

- The gate reads `X-Forwarded-For` only when the peer is on the list. A peer
  that is not on the list is the client, whatever the header says.
- The gate reads the header from the right, and takes the first entry that is
  not on the list. Each proxy appends the address that it saw, so the entries
  to the left of that entry are what the client wrote.
- An entry that is not an IP address stops the walk. The key is then the last
  trusted hop, not a text that the client chose.
- When each entry is on the list, the key is the left-most entry.
- A port on an entry (`203.0.113.7:51234`, `[2001:db8::1]:443`) is removed.
  An IPv4-mapped IPv6 address is compared as its IPv4 address.
- A network with host bits (`10.0.0.1/24`) or a name is a setup error. The gate
  logs it, trusts no proxy and stays on (constitution III).

The log line `authentication failure from <IP>` names this key, so fail2ban and
crowdsec see the client behind the proxy. The text of the line does not change.

## Alternatives

- **Always take the right-most entry.** This breaks a chain of two proxies,
  for example Cloudflare in front of the RunPod proxy, and it changes the
  default for each current user.
- **Read RFC 7239 `Forwarded: for=`.** Caddy, Traefik and the RunPod proxy send
  `X-Forwarded-For`. A second header with its own trust rules adds a way to get
  the rules wrong for no current user.
- **Trust private networks by default.** A LAN client could then choose its own
  key on a host that serves ComfyUI to the LAN.

## Consequences

- Behind a trusted proxy, each client gets its own wait, and a client that
  avoids the proxy cannot choose its key.
- The gate can only use the address that the proxy saw. When the proxy itself
  sees each client at one address, for example behind rootless port forwarding,
  the clients still share one wait. The fix is then at the proxy.
