Feature: The Bearer path accepts OIDC access tokens

  Scenario: A valid access token
    Given the mode is on
    When a program sends a valid access token
    Then the gate gives the answer of ComfyUI

  Scenario: A real rauthy token
    Given a real rauthy
    When a program sends a client_credentials token for the audience
    Then GET /queue gives HTTP 200

  Scenario: A rauthy token for another resource
    Given a real rauthy
    When a program sends a token for another resource
    Then GET /queue gives HTTP 401

  Scenario: The ws handshake with a valid token
    Given the mode is on
    When a program opens /ws with a valid access token
    Then the gate lets the handshake through

  Scenario: The ws handshake with a refused token
    Given the mode is on
    When a program opens /ws with a refused token
    Then the gate gives HTTP 401 before the upgrade

  Scenario: No audience
    Given no audience
    When ComfyUI starts
    Then the mode is off

  Scenario: The static credential with the mode on
    Given the mode is on
    When a program sends the static credential
    Then the gate gives the answer of ComfyUI

  Scenario: An audience with no issuer is a start error
    Given an audience with no issuer
    When ComfyUI starts
    Then the gate writes a start error

  Scenario: An audience with no issuer keeps the gate on
    Given an audience with no issuer
    When ComfyUI starts
    Then the credential gate stays on

  Scenario: Key confusion
    Given an HS256 token signed with the public key
    When the gate checks it
    Then the gate gives HTTP 401

  Scenario: alg none
    Given a token with alg none
    When the gate checks it
    Then the gate gives HTTP 401

  Scenario: An ID token
    Given an ID token with typ JWT and no scope
    When the gate checks it
    Then the gate gives HTTP 401

  Scenario: A token of 2 hours
    Given a token that lives 2 hours
    When the gate checks it
    Then the gate gives HTTP 401

  Scenario: An expired token
    Given a token that expired 1 second ago
    When the gate checks it
    Then the gate gives HTTP 401

  Scenario: Another audience
    Given a token for another audience
    When the gate checks it
    Then the gate gives HTTP 401

  Scenario: No required scope
    Given a token with no required scope
    When the gate checks it
    Then the gate gives HTTP 401

  Scenario: The log line of a refused token
    Given a refused token
    When the gate refuses it
    Then the log line names the reason and holds no part of the token

  Scenario: A refused token counts
    Given a refused token
    When the gate refuses it
    Then the address gets one failure in the rate limit

  Scenario: One read of the keys
    Given ten valid tokens
    When the gate checks them
    Then the gate reads the JWKS one time

  Scenario: A key rotation
    Given a new key at the issuer
    When a token with its kid comes
    Then the gate reads the JWKS again and accepts the token

  Scenario: The 60-second limit
    Given a read less than 60 seconds ago
    When a token with an unknown kid comes
    Then the gate does not read the JWKS

  Scenario: No read for a cheap refusal
    Given a bad shape, another issuer or a refused alg
    When the gate checks the token
    Then the gate does not read the JWKS

  Scenario: comfy-mcp retries after a 401
    Given a refused token
    When a valid token comes from the same address within one second
    Then the gate gives the answer of ComfyUI

  Scenario: Two refused tokens
    Given a refused token
    When a second refused token comes within one second
    Then the gate gives HTTP 429
