Feature: Docker ComfyUI integration harness

  Scenario: Boot a real, gated ComfyUI instance
    Given Docker is available and the repo is checked out
    When the developer brings the harness up
    Then a local ComfyUI instance becomes reachable and reports healthy once the gate is enforcing

  Scenario: Unauthenticated HTTP requests are rejected
    Given the harness is healthy
    When an unauthenticated request is made to it
    Then the request is rejected with 401

  Scenario: The fixed test credential succeeds
    Given the harness is healthy
    When a request is made with the fixed test credential
    Then the request succeeds

  Scenario: The websocket handshake is gated too
    Given the harness is healthy
    When an unauthenticated websocket handshake is attempted against /ws
    Then the handshake is rejected

  Scenario: Repeated wrong credentials trigger backoff
    Given the harness is healthy
    When the integration suite submits repeated wrong credentials
    Then it observes increasing backoff consistent with the gate's rate-limiting behavior

  Scenario: Teardown and restart leave no stale state
    Given the harness was previously brought up and torn down
    When it is brought up again
    Then it behaves identically to a first-ever run, with no stale rate-limit counters or sessions

  Scenario: The gate's absence is detected, not silently passed
    Given the gate's middleware is not actually wired up
    When the integration suite runs
    Then it fails loudly rather than passing silently
