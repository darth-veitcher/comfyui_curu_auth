Feature: US3 - Programs and log tools see no change

  Scenario: A wrong Bearer header
    Given a program sends a wrong Bearer header
    When the gate rejects it
    Then the status and the body are the same as before

  Scenario: The static credential
    Given a program sends the static credential
    When the gate accepts it
    Then the program gets the answer of ComfyUI

  Scenario: The log line
    Given a rejected request
    When the gate writes its log line
    Then the line matches the patterns in contrib/
