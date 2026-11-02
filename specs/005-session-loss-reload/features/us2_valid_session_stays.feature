Feature: US2 - A tab with a valid session stays on its page

  Scenario: Another node gives HTTP 401
    Given a valid session
    When ComfyUI or another node gives HTTP 401
    Then the tab stays on its page

  Scenario: The server cannot be reached
    Given a valid session
    When the server cannot be reached
    Then the tab stays on its page

  Scenario: The server comes back with the session
    Given the server cannot be reached
    When the server comes back with the session
    Then the tab stays on its page

  Scenario: The socket closes for another reason
    Given a valid session
    When the /ws socket closes for a reason other than the gate
    Then the tab stays on its page
