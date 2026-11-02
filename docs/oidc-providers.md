# Connect an identity provider

This page tells you how to connect the browser login, and the access tokens of programs, to an identity provider with OpenID Connect (OIDC). It gives what the gate needs from any identity provider, and notes for eight of them. The [glossary of the README](../README.md#glossary) explains each term. The [README](../README.md#log-in-through-your-identity-provider) gives the settings.

Each fact has a source:

- **Tested live**: a test of this repository runs it against the real provider.
- **Provider documentation**: the fact comes from the documentation of the provider. No test of this repository runs it.

## Check what the gate needs from any provider

The gate is a confidential client. It uses the authorization code flow: the browser brings back a code, and the gate exchanges the code for an ID token. PKCE (S256) protects the code. A valid ID token gives a session cookie.

| Need | How to check it |
|---|---|
| A discovery document at `<issuer>/.well-known/openid-configuration` | Open the URL. Its `issuer` must equal your issuer setting, character for character, with the same `/` at the end. |
| `https` for the issuer and each endpoint | The issuer, `authorization_endpoint`, `token_endpoint` and `jwks_uri` must use `https`. The gate allows plain `http` only on `localhost`, `127.0.0.1` and `::1`. The gate follows no redirect. |
| An asymmetric signing key | The ID token must use RS256, RS384, RS512, PS256, ES256 or EdDSA. The gate refuses `none` and HS256, HS384 and HS512. |
| `exp` and `iat` in the ID token | The gate refuses an ID token without them. |
| `azp` (the authorized party) equal to the client id | This applies when the ID token has more than one audience (`aud`), or has `azp`. |
| A clock that is correct to 60 seconds | The gate allows 60 seconds of difference for `exp`, `iat` and `nbf` (the first valid time). |
| A redirect URI of `https://<your ComfyUI host>/curu-auth/oidc/callback` | Register it on the client. Use the same value for `COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI`. For more than one address, register one URI for each address, and give all of them in the setting. |

To find the issuer, open the discovery document of the provider and copy its `issuer` value. Do not remove or add a `/` at the end.

## Choose who can log in

A valid login at the identity provider is not enough. The gate also needs an allowlist, or the OIDC login stays off.

| Setting | Use it when |
|---|---|
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS` | You know the `sub` value of each person. This is the most stable choice. |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_EMAILS` | The provider sends `email_verified: true`. An email that is not verified never matches. |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_DOMAIN` | Each person in one Google Workspace domain can log in. The gate compares it with the `hd` claim. |
| `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true` | The identity provider already limits who can log in, for example with a group binding. |

Read the `sub` of a person at the identity provider. The sections for rauthy, Authentik, Keycloak, Auth0 and Okta say where. The gate never writes a `sub` to its log.

## Use rauthy

| Fact | Source |
|---|---|
| The issuer is `http://<host>/auth/v1/` with a `/` at the end. | Tested live (0.37.2) |
| Behind TLS, the issuer is `https://<host>/auth/v1/`. | Provider documentation |
| Make a confidential client with the flow `authorization_code` and the PKCE challenge `S256`. | Tested live (0.37.2) |
| Set `id_token_alg` of the client. The gate accepts EdDSA and RS256, RS384 and RS512. | Tested live with EdDSA (0.37.2) |
| A user with an email, a password and a `given_name` logs in. | Tested live (0.37.2) |
| The login page asks for the email first, and then for the password. | Tested live (0.37.2) |
| The `sub` of a person is the `id` of the user. | Tested live (0.37.2) |
| The admin interface shows the `id` of each user. | Provider documentation |
| rauthy reads its bootstrap files only at its first start. | Provider documentation |

## Use Authentik

| Fact | Source |
|---|---|
| The issuer is `https://<host>/application/o/<application slug>/`, with a `/` at the end. | Provider documentation |
| Make an OAuth2/OpenID provider with the client type "Confidential". | Provider documentation |
| **Select a signing key on the provider.** Without one, Authentik signs with HS256 and the client secret. The gate refuses that token, and its log line names the signing key. | Provider documentation |
| Use a strict redirect URI, not a regular expression that matches other hosts. | Provider documentation |
| **Bind the application to a group.** Without a policy binding, each user of Authentik can log in to the application. | Provider documentation |
| Set `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true` only when the group binding is in place. | Provider documentation |
| The `sub` depends on the "Subject mode" of the provider. The default is a hash of the user id. | Provider documentation |
| Check that `email_verified` is `true` in your ID tokens before you use `ALLOWED_EMAILS`. | Provider documentation |

## Use Keycloak

| Fact | Source |
|---|---|
| The issuer is `https://<host>/realms/<realm>`, with no `/` at the end. | Provider documentation |
| Make an OpenID Connect client with "Client authentication" on and the "Standard flow". | Provider documentation |
| Set "PKCE Method" to `S256` in the advanced settings of the client. | Provider documentation |
| The realm signs with RS256 by default. | Provider documentation |
| The `sub` is the user ID on the "Details" tab of the user. | Provider documentation |
| `email_verified` is the "Email verified" switch of the user. | Provider documentation |

## Use Auth0

| Fact | Source |
|---|---|
| The issuer is `https://<tenant>.<region>.auth0.com/` with a `/` at the end, or your custom domain. Copy it from the discovery document. | Provider documentation |
| Make a "Regular Web Application". | Provider documentation |
| Keep the signing algorithm of the application at RS256. The gate refuses HS256. | Provider documentation |
| The `sub` has the form `<connection>\|<id>`, for example `auth0\|abc123`. | Provider documentation |

## Use Okta

| Fact | Source |
|---|---|
| The issuer is `https://<org>.okta.com` for the org authorization server, or `https://<org>.okta.com/oauth2/default` for the default custom server. | Provider documentation |
| Make an "OIDC - OpenID Connect" app of the type "Web Application". | Provider documentation |
| Okta signs ID tokens with RS256. | Provider documentation |
| The `sub` is the Okta user id, for example `00u1abcd2EFGH3ijk4l5`. | Provider documentation |

## Use Microsoft Entra ID

| Fact | Source |
|---|---|
| The issuer is `https://login.microsoftonline.com/<tenant id>/v2.0`, for one tenant only. | Provider documentation |
| A multi-tenant app (`common` or `organizations`) is not supported. Its discovery document has the issuer `https://login.microsoftonline.com/{tenantid}/v2.0` as a template, so the gate refuses it. | Provider documentation |
| Register a web application with a client secret. | Provider documentation |
| Entra ID signs ID tokens with RS256. | Provider documentation |
| The `sub` is different for each application. Use `ALLOWED_SUBJECTS`, or `ALLOW_ANY_USER=true` with "Assignment required" on the enterprise application. | Provider documentation |
| Do not use `ALLOWED_EMAILS`, because the email of an Entra ID account is not always verified. | Provider documentation |

## Use Google

| Fact | Source |
|---|---|
| The issuer is `https://accounts.google.com`, with no `/` at the end. | Provider documentation |
| **Each Google account in the world can log in to a Google client.** Always set `ALLOWED_SUBJECTS`, `ALLOWED_EMAILS` or `ALLOWED_DOMAIN`. Never set `ALLOW_ANY_USER=true` for Google. | Provider documentation |
| Make an OAuth client ID of the type "Web application". | Provider documentation |
| Google signs ID tokens with RS256. | Provider documentation |
| A Gmail address has `email_verified: true`, so `ALLOWED_EMAILS` works. | Provider documentation |
| Only a Google Workspace account has the `hd` claim. Use `ALLOWED_DOMAIN` for a Workspace domain only. | Provider documentation |
| Google can also write `iss` as `accounts.google.com`, with no scheme. The gate refuses that form, because `iss` must equal the issuer exactly. The authorization code flow gives the `https` form. | Provider documentation |

## Use Authelia

| Fact | Source |
|---|---|
| The issuer is `https://<host>`, with no `/` at the end. | Tested live (4.39.20) |
| Register a confidential client (`public: false`). Authelia checks the PKCE S256 that the gate sends. | Tested live (4.39.20) |
| Authelia signs ID tokens with RS256. | Tested live (4.39.20) |

## Let programs send access tokens

A program can send an access token of the identity provider in the Bearer header. The [README](../README.md#let-a-program-call-comfyui-with-an-access-token) gives the settings. The gate checks each token itself, with the keys of the identity provider.

| Need | How to check it |
|---|---|
| A grant for a program with no person, usually `client_credentials` | The discovery document lists it in `grant_types_supported`. |
| A JWT access token | A JWT has three parts with a `.` between them. An opaque token cannot pass. |
| A fixed `aud` value for this gate | Set `COMFYUI_CURU_AUTH_OIDC_AUDIENCE` to it. |
| A lifetime of 1 hour or less | `exp` minus `iat` of a token. |
| `typ` `at+jwt`, or a client id and a scope | A token of the type `JWT`, or with no `typ`, needs `azp`, `client_id` or `cid`, and `scope` or `scp`. |

### rauthy

| Fact | Source |
|---|---|
| Make a confidential client with the flow `client_credentials`. | Tested live (0.37.2) |
| Send the client secret in the form. rauthy 0.37.2 refuses HTTP Basic on this grant. | Tested live (0.37.2) |
| Send `resource=<audience>` in the token request. rauthy then puts it in `aud`, and the gate accepts the token. | Tested live (0.37.2) |
| Set `allowed_resources` of the client with the admin API. | Tested live (0.37.2) |
| A token for another resource has another `aud`. The gate refuses it with HTTP 401. | Tested live (0.37.2) |
| A token with no `resource` does not hold the audience in `aud`. The gate refuses it. | Tested live (0.37.2) |
| rauthy refuses a `resource` that is not in `allowed_resources`, with `invalid_target`. | Tested live (0.37.2) |
| A `client_credentials` token holds the `default_scopes` of the client. Put each required scope in `default_scopes`. | Tested live (0.37.2) |
| A `client_credentials` token has `typ` `at+jwt`. | Tested live (0.37.2) |

### Authentik

| Fact | Source |
|---|---|
| Make one OAuth2 provider only for this gate. `aud` is its client id, so set the audience to that client id. | Provider documentation |
| **Select a signing key on the provider.** Without one, the token is HS256, and the gate refuses it. | Provider documentation |
| An access token has `typ` `JWT` and `azp`. An ID token has no `scope`, and the gate refuses it. | Provider documentation |
| **Ask for a scope in the token request**, for example `scope=openid`. The `scope` of the token holds only the scopes of the request. With no scope, the gate refuses the token as `ID token or no client id and scope`. | Provider documentation |
| A program uses `client_credentials` with the client id, the user name of a service account, and an app password. | Provider documentation |
| **Bind the application to a group**, and put the service account in it. | Provider documentation |
| Set the access token validity of the provider to 1 hour or less, for example `minutes=10`. | Provider documentation |

### Keycloak

| Fact | Source |
|---|---|
| Add an Audience mapper to a client scope of the program client, with "Add to access token" on. Its value is the audience. | Provider documentation |
| Turn on "Client authentication" and "Service account roles" on the client of the program. | Provider documentation |
| An access token has `typ` `JWT`, `azp` and `scope`, so it passes. | Provider documentation |

### Auth0

| Fact | Source |
|---|---|
| Make an API. Its Identifier is the `aud` of each token for it, so set the audience to that Identifier. | Provider documentation |
| Authorize a machine-to-machine application for the API. It sends `audience=<Identifier>` in each token request. | Provider documentation |
| Give the API the RS256 algorithm. | Provider documentation |
| Grant the application at least one permission on the API. Without one, the token has no `scope`, and the gate refuses it as an ID token. | Provider documentation |

### Okta

| Fact | Source |
|---|---|
| Use a custom authorization server. Its Audience setting is the audience. | Provider documentation |
| A `client_credentials` request needs a custom scope. A request for `openid` alone fails. | Provider documentation |
| An access token has no `typ`, `cid` as the client id and `scp` as a list, so it passes. | Provider documentation |

### Microsoft Entra ID

| Fact | Source |
|---|---|
| **Not supported for programs.** A `client_credentials` token has `roles` but no `scp`. Its type is `JWT`, so the gate refuses it. | Provider documentation |

### Google

| Fact | Source |
|---|---|
| **Not supported for programs.** Google access tokens are opaque, and Google has no `client_credentials` grant. | Provider documentation |

### Connect comfy-mcp

comfy-mcp gets its own token for each backend. Give the backend an `oidc` table in the configuration file of comfy-mcp. This example is for rauthy, with the gate at `https://comfyui.example.com`:

```toml
[backends.gated]
url = "https://comfyui.example.com"

[backends.gated.oidc]
issuer = "https://idp.example.com/auth/v1/"
client_id = "comfy-mcp-backend"
client_secret_env = "GATED_OIDC_SECRET"
resource = "https://comfyui.example.com"
```

Set `COMFYUI_CURU_AUTH_OIDC_AUDIENCE` of the gate to the same URL as `resource`. Put the client secret in the variable that `client_secret_env` names.

| Fact | Source |
|---|---|
| comfy-mcp 0.1.0 with this table reads the queue through the gate, with its own token. `list_backends` shows the backend as online. | Tested live (rauthy 0.37.2) |
| comfy-mcp sends the same token on the `/ws` handshake, and the gate lets it through. | Tested live (rauthy 0.37.2) |
| With a token for another resource, `get_queue` gives `backend_auth_failed`, not `backend_rate_limited`. The gate refuses the first try and the one retry of comfy-mcp for the wrong audience. The retry falls in the wait of the gate and still gets 401. | Tested live (rauthy 0.37.2) |

## Fix a login or an access token that fails

The gate writes one line for each login that the callback refuses, and for each refused access token. The reason follows `oidc callback:` or `token refused:`. The line never holds a token or a claim value. A fault at the start of the login gives HTTP 503 and a line with `OIDC login unavailable:`.

| Message | Fix |
|---|---|
| `OIDC login is off: set ...` at start | Set an allowlist, or `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true`. |
| `OIDC login is off: ... must use https` at start | Use an `https` issuer, or a loopback host. |
| `OIDC login unavailable: ... names the issuer ...` | Copy the `issuer` value exactly from the discovery document, with its `/`. |
| `OIDC login unavailable: ... must use https` | Make each endpoint of the identity provider `https`. |
| `discovery document refused` | At the callback, the gate could not read the discovery document, or the document failed a check. Make sure that the identity provider is available, fix the document as above, and try again. |
| `the JWKS is not a valid key set` or `failed to fetch the JWKS` | Open `jwks_uri` of the discovery document, and check that it gives the keys with no redirect. |
| `algorithm HS256 is not allowed ... select a signing key` | Select a signing key on the provider. This is the usual Authentik fault. |
| `the person is not on the allowlist` | Add the `sub`, the verified email or the domain of the person. |
| `the azp of the ID token is not this client` | Check that the client id setting is the client id of the provider. |
| `token refused: wrong audience` | Set `COMFYUI_CURU_AUTH_OIDC_AUDIENCE` to the `aud` of the tokens, or make the identity provider put it there. |
| `token refused: expired`, `not yet valid` or `lifetime too long` | Check the clocks, and set the token lifetime to 1 hour or less. |
| `token refused: ID token or no client id and scope` | Send an access token, not an ID token. Give the client a scope. |
| `token refused: missing scope` | Give the client each scope of `COMFYUI_CURU_AUTH_OIDC_REQUIRED_SCOPES`. |
| `token refused: wrong issuer` or `wrong token type` | Get the token from the configured issuer, as an access token. |
| `token refused: missing claim` | The token has no `iss`, `aud`, `exp` or `iat`. Make the identity provider put each one in the access token. |
| `token refused: bad signature`, `malformed token` or an algorithm reason | The token is not from a key of the issuer. Get a new token. |
| `identity provider unavailable` (HTTP 503) | The gate has no keys of the issuer. Look for `cannot read the OIDC keys` in the log. |
| `cannot read the OIDC keys` | Make sure that the identity provider is available. The gate tries again after 60 seconds at the earliest. |
| `unknown key` | The identity provider changed its keys: try again after 60 seconds. Or the token has no `kid`, and the JWKS has more than one signing key. Then make the identity provider send `kid`. |
