# Blocking repeat offenders at the firewall

Every rejected request writes one stable, greppable log line:

```
comfyui_curu_auth: authentication failure from 203.0.113.7 (GET /object_info)
comfyui_curu_auth: authentication failure from 203.0.113.7 (login form)
comfyui_curu_auth: authentication failure from 203.0.113.7 (oidc callback: the person is not on the allowlist)
comfyui_curu_auth: authentication failure from 203.0.113.7 (GET /queue: token refused: expired)
```

The patterns below match the prefix `authentication failure from <IP>`, so each form matches. An outage of the identity provider writes `identity provider unavailable` or `OIDC login unavailable` instead, and these patterns do not match it.

The gate has no ban list of its own. These files connect that log line
to a real IP-blocking tool. That tool blocks repeat offenders at the
network, outside the ComfyUI process. Pick one.

## fail2ban

1. Copy the filter:
   ```bash
   cp fail2ban/comfyui-curu-auth.conf /etc/fail2ban/filter.d/comfyui-curu-auth.conf
   ```
2. Verify the regex against your own log lines before relying on it —
   no live jail needed to check this:
   ```bash
   fail2ban-regex /path/to/comfyui/output.log fail2ban/comfyui-curu-auth.conf
   ```
3. Copy the jail definition, and set its `logpath`. If ComfyUI logs to
   the systemd journal, use the `journalmatch` line in place of it:
   ```bash
   cp fail2ban/jail-comfyui-curu-auth.local /etc/fail2ban/jail.d/comfyui-curu-auth.local
   ```
4. Restart fail2ban and confirm the jail is active:
   ```bash
   systemctl restart fail2ban
   fail2ban-client status comfyui-curu-auth
   ```

`maxretry`, `findtime` and `bantime` in the jail file are standard
fail2ban options. As shipped, 5 failures in 10 minutes give a ban of 1
hour. Change them as for any other jail.

## crowdsec

1. Copy the parser and scenario into crowdsec's own hub-managed
   directories:
   ```bash
   cp crowdsec/parsers/comfyui-curu-auth.yaml /etc/crowdsec/parsers/s01-parse/comfyui-curu-auth.yaml
   cp crowdsec/scenarios/comfyui-curu-auth-bruteforce.yaml /etc/crowdsec/scenarios/comfyui-curu-auth-bruteforce.yaml
   ```
2. Point crowdsec's own `acquis.yaml` at the same log source
   (ComfyUI's stdout/log file, or its systemd unit if journal-based),
   e.g.:
   ```yaml
   filenames:
     - /path/to/comfyui/output.log
   labels:
     type: syslog
   ```
3. Reload crowdsec and confirm the scenario is registered:
   ```bash
   systemctl reload crowdsec
   cscli scenarios list
   ```
4. Make sure that the parser and the scenario match a real log line
   before you use them in production. They follow the documented YAML
   syntax of crowdsec, but no test ran them against a live crowdsec:
   ```bash
   cscli explain --file /path/to/comfyui/output.log --type syslog
   ```

If step 4 does not show `comfyui_curu_auth_auth_fail` and the
`comfyui-curu-auth/bruteforce` scenario on repeated lines, check the log
path in `acquis.yaml` first. A wrong path is the usual reason that a
correct parser sees no events.
