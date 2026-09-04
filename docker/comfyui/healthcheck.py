"""Docker HEALTHCHECK for the ComfyUI harness.

Requires 401 specifically -- NOT curu's own tolerant version (which treats
200 as healthy too, since its node is baked into the image and always
present). This harness's entire premise is a bind mount
(docker-compose.yml mounts this repo's own working tree into
custom_nodes/comfyui_curu_auth) that can fail -- an unmounted or
failed-to-import node leaves ComfyUI ungated, answering 200. Treating that
as "healthy" would silently defeat FR-004 ("distinguishes 'the gate is
actively enforcing' from ... 'gate isn't wired up'"), the whole reason this
harness's health signal exists.

This check used to accept 429 alongside 401, because its own
unauthenticated probe -- repeated every ``interval`` -- was itself counted
as a failed authentication attempt by ``gate.py``'s ``RateLimiter``, so
after enough probes its own client key was blocked and every later probe
got 429 rather than 401. That was a workaround for a defect, not a
property of the system: the gate now records a failure only for a request
that actually *offered* a credential and got it wrong (see
``build_gate_middleware``'s own docstring), and this probe offers none, so
it can no longer rate-limit itself no matter how long it polls.

With the cause gone, keeping the workaround would be actively harmful: a
429 here now means some *other* client sharing this key (127.0.0.1 --
inside the container) really is locked out, which is exactly the condition
an operator needs to see rather than have reported as healthy. So 401 is
the only healthy answer; 429, 200 (ungated), and a connection failure
(ComfyUI not up) are all unhealthy.
"""

import sys
import urllib.error
import urllib.request

try:
    response = urllib.request.urlopen("http://localhost:8188/")
except urllib.error.HTTPError as exc:
    sys.exit(0 if exc.code == 401 else 1)
else:
    # A 200 (or anything else that doesn't raise) means the gate did not
    # reject this unauthenticated request -- ungated, not healthy.
    response.close()
    sys.exit(1)
