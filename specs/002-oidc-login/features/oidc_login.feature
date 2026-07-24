Feature: OIDC/OAuth login path

  Scenario: Initiate login redirects to the identity provider
    Given OIDC is configured
    When the operator initiates login via the OIDC option
    Then they are redirected to their identity provider to authenticate

  Scenario: Successful provider login establishes a session
    Given the operator successfully authenticates at the identity provider
    When they are redirected back
    Then they land on ComfyUI's UI in an authenticated session using the same session mechanism as the credential login

  Scenario: Cancelled or failed provider login does not authenticate
    Given the operator cancels or fails authentication at the identity provider
    When they return to ComfyUI
    Then they are not authenticated and see an appropriate message

  Scenario: No OIDC routes or behavior when unconfigured
    Given no OIDC configuration is present
    When ComfyUI starts
    Then no OIDC-related routes or behavior are exposed and startup succeeds exactly as today

  Scenario: Existing credential and login form are unaffected
    Given OIDC is unconfigured
    When an operator uses the existing credential or login form
    Then behavior is unchanged from before this feature existed

  Scenario: Repeated failed OIDC attempts trigger backoff
    Given repeated failed OIDC authentication attempts from the same client
    When they occur
    Then the same rate-limit backoff already applied to the credential and login-form paths also applies here

  Scenario: Failed OIDC attempts are logged like other paths
    Given a failed OIDC attempt is rejected
    When it happens
    Then a stable, greppable log line is emitted matching the existing fail2ban/crowdsec-compatible format

  Scenario: A completed authorization attempt cannot be replayed
    Given a state/code pair that already succeeded once
    When it is submitted again verbatim
    Then the second attempt is rejected, not accepted

  Scenario: The login-initiation route is rate-limited and bounded like other unauthenticated paths
    Given the OIDC login-initiation route is reachable without a session
    When it is hit repeatedly by an unauthenticated caller
    Then the same rate-limiting applies and in-flight state does not grow without bound
