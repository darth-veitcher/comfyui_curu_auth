Feature: US1 - The tab goes to the login page after a restart

  Scenario: The session store loses the session
    Given a tab with a valid session
    When the session store loses the session
    Then the tab shows the login page within 5 seconds

  Scenario: The gate rejects a poll
    Given a tab that polls /api/jobs
    When the gate rejects the poll
    Then the tab goes to the login page

  Scenario: The gate rejects the ws handshake
    Given an idle tab with only the /ws socket
    When the gate rejects the /ws handshake
    Then the tab goes to the login page

  Scenario: No new log line after the move
    Given the tab shows the login page
    When 60 seconds pass
    Then the log has no new "authentication failure" line from the tab

  Scenario: The user logs in again
    Given the tab shows the login page
    When the user logs in
    Then the tab shows ComfyUI at /

  Scenario: An OIDC session is lost
    Given OIDC is on
    When the session of an OIDC login is lost
    Then the tab goes to the login page
