Feature: The OIDC login works with rauthy, Authentik and other providers

  Scenario: An issuer with a slash at the end
    Given an issuer that ends in "/"
    When the gate reads the discovery document
    Then the discovery URL has no "//"

  Scenario: The iss of the ID token is the configured issuer
    Given a discovery document that names the configured issuer
    When a person logs in
    Then the gate accepts an ID token whose iss is that issuer

  Scenario: A discovery document that names another issuer
    Given a discovery document that names another issuer
    When a person starts a login
    Then the gate refuses the login

  Scenario: An EdDSA ID token
    Given an ID token signed with EdDSA
    When the gate checks it
    Then the gate accepts the token

  Scenario: A real rauthy login
    Given a real rauthy with an EdDSA client
    When a person logs in through a browser
    Then the browser gets the curu_auth cookie

  Scenario: A listed subject
    Given an allowlist of subjects
    When a person with a listed sub logs in
    Then the gate gives a session

  Scenario: A subject that is not listed
    Given an allowlist of subjects
    When a person with another sub logs in
    Then the gate gives HTTP 401 and writes the failure log line

  Scenario: An email that is not verified
    Given an allowlist of emails
    When the ID token has a listed email but email_verified is not true
    Then the gate refuses the login

  Scenario: An allowed domain
    Given an allowed domain
    When the hd claim of the ID token is that domain
    Then the gate gives a session

  Scenario: No allowlist
    Given a full OIDC setup with no allowlist and no ALLOW_ANY_USER
    When ComfyUI starts
    Then the OIDC routes do not exist and the credential gate stays on

  Scenario: Any user
    Given ALLOW_ANY_USER=true
    When any person logs in at the provider
    Then the gate gives a session

  Scenario: alg none
    Given an ID token with alg none
    When the gate checks it
    Then the gate refuses the token

  Scenario: Key confusion
    Given an HS256 ID token signed with the public key as the HMAC secret
    When the gate checks it
    Then the gate refuses the token

  Scenario: The HS256 reason
    Given an HS256 ID token
    When the gate refuses it
    Then the reason says that the Authentik provider has no signing key

  Scenario: An http endpoint
    Given a discovery document with an http endpoint on a host that is not loopback
    When a person starts a login
    Then the gate refuses the login

  Scenario: No exp or no iat
    Given an ID token with no exp or no iat
    When the gate checks it
    Then the gate refuses the token

  Scenario: A wrong azp
    Given an ID token with two audiences and an azp that is not the client id
    When the gate checks it
    Then the gate refuses the token

  Scenario: The clock leeway
    Given an ID token that expired 30 seconds ago
    When the gate checks it
    Then the gate accepts the token because of the clock leeway

  Scenario: The default scopes
    Given no scopes setting
    When the gate builds the authorization URL
    Then the scope is "openid profile email"

  Scenario: A scopes setting
    Given the scopes setting "profile"
    When the gate builds the authorization URL
    Then the scope is "openid profile"
