# Connect an identity provider

This page tells you how to connect the browser login of comfyui_curu_auth to an identity provider with OpenID Connect (OIDC). It gives what the gate needs from any identity provider, and notes for eight of them. The [glossary of the README](../README.md#glossary) explains each term. The [README](../README.md#log-in-through-your-identity-provider) gives the settings.

Each fact has a source:

- **Tested live**: a test of this repository runs it against the real provider.
- **Provider documentation**: the fact comes from the documentation of the provider. No test of this repository runs it.

## Check what the gate needs from any provider

The gate is a confidential client. It uses the authorization code flow: the browser brings back a code, and the gate exchanges the code for an ID token. PKCE (S256) protects the code. A valid ID token gives a session cookie.

| Need | How to check it |
|---|---|
| A discovery document at `<issuer>/.well-known/openid-configuration` | Open the URL. Its `issuer` must equal your issuer setting, character for character, with the same `/` at the end. |
| `https` for the issuer and each endpoint | The issuer, `authorization_endpoint`, `token_endpoint` and `jwks_uri` must use `https`. Plain `http` is allowed only on `localhost`, `127.0.0.1` and `::1`. The gate follows no redirect. |
| An asymmetric signing key | The ID token must use RS256, RS384, RS512, PS256, ES256 or EdDSA. The gate refuses `none` and HS256, HS384 and HS512. |
| `exp` and `iat` in the ID token | The gate refuses an ID token without them. |
| `azp` (the authorized party) equal to the client id | This applies when the ID token has more than one audience (`aud`), or has `azp`. |
| A clock that is correct to 60 seconds | The gate allows 60 seconds of difference for `exp`, `iat` and `nbf` (the first valid time). |
| A redirect URI of `https://<your ComfyUI host>/curu-auth/oidc/callback` | Register it on the client. Use the same value for `COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI`. |

To find the issuer, open the discovery document of the provider and copy its `issuer` value. Do not remove or add a `/` at the end.

## Choose who can log in

A valid login at the identity provider is not enough. The gate also needs an allowlist, or the OIDC login stays off.

| Setting | Use it when |
|---|---|
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS` | You know the `sub` value of each person. This is the most stable choice. |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_EMAILS` | The provider sends `email_verified: true`. An email that is not verified never matches. |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_DOMAIN` | Each person in one Google Workspace domain can log in. The gate compares it with the `hd` claim. |
| `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true` | The identity provider already limits who can log in, for example with a group binding. |

Read the `sub` of a person at the identity provider. Each section below says where. The gate never writes a `sub` to its log.

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

## Fix a login that fails

The gate writes one line for each login that the callback refuses. The reason follows `oidc callback:`. The line never holds a token or a claim value. A fault at the start of the login gives HTTP 503 and a line with `OIDC login unavailable:`.

| Message | Fix |
|---|---|
| `OIDC login is off: set ...` at start | Set an allowlist, or `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true`. |
| `OIDC login is off: ... must use https` at start | Use an `https` issuer, or a loopback host. |
| `OIDC login unavailable: ... names the issuer ...` | Copy the `issuer` value exactly from the discovery document, with its `/`. |
| `OIDC login unavailable: ... must use https` | Make each endpoint of the identity provider `https`. |
| `discovery document refused` | The discovery document changed during the login. Fix it as above, and try again. |
| `the JWKS is not a valid key set` or `failed to fetch the JWKS` | Open `jwks_uri` of the discovery document, and check that it gives the keys with no redirect. |
| `algorithm HS256 is not allowed ... select a signing key` | Select a signing key on the provider. This is the usual Authentik fault. |
| `the person is not on the allowlist` | Add the `sub`, the verified email or the domain of the person. |
| `the azp of the ID token is not this client` | Check that the client id setting is the client id of the provider. |
| `unknown key` | The provider changed its keys during the login. Try again. |
