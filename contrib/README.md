# Blocking repeat offenders at the firewall

Every rejected request writes one stable, greppable log line:

```
comfyui_curu_auth: authentication failure from 203.0.113.7 (GET /object_info)
comfyui_curu_auth: authentication failure from 203.0.113.7 (login form)
```

The gate itself has no ban list of its own — these files wire that log
line into a real IP-blocking tool instead, so repeat offenders get
blocked at the network level, entirely outside this process. Pick one.

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
3. Copy the jail definition, then edit its `logpath` (or switch to the
   commented-out `journalmatch` line if ComfyUI logs to the systemd
   journal instead of a file):
   ```bash
   cp fail2ban/jail-comfyui-curu-auth.local /etc/fail2ban/jail.d/comfyui-curu-auth.local
   ```
4. Restart fail2ban and confirm the jail is active:
   ```bash
   systemctl restart fail2ban
   fail2ban-client status comfyui-curu-auth
   ```

`maxretry`/`findtime`/`bantime` in the jail file are fail2ban's own
standard options (5 failures inside 10 minutes bans for 1 hour, as
shipped) — tune them the same way you would for any other jail.

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
4. Confirm the parser/scenario actually match a real log line before
   trusting it in production — this pair follows crowdsec's own
   documented YAML syntax but hasn't been exercised against a live
   crowdsec instance itself:
   ```bash
   cscli explain --file /path/to/comfyui/output.log --type syslog
   ```

If step 4 doesn't show `comfyui_curu_auth_auth_fail` being parsed and
the `comfyui-curu-auth/bruteforce` scenario triggering on repeated
lines, check `acquis.yaml`'s log source path first — that's the most
common reason a correctly-installed parser never sees any events.
