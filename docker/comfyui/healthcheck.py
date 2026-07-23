"""Docker HEALTHCHECK for the ComfyUI harness.

Requires 401 or 429 specifically -- NOT curu's own tolerant version (which
treats 200 as healthy too, since its node is baked into the image and
always present). This harness's entire premise is a bind mount
(docker-compose.yml mounts this repo's own working tree into
custom_nodes/comfyui_curu_auth) that can fail -- an unmounted or
failed-to-import node leaves ComfyUI ungated, answering 200. Treating that
as "healthy" would silently defeat FR-004 ("distinguishes 'the gate is
actively enforcing' from ... 'gate isn't wired up'"), the whole reason this
harness's health signal exists.

429 is included alongside 401 -- discovered live: this check's own
unauthenticated probe, repeated every ``interval``, counts as a failure
against ``gate.py``'s ``RateLimiter`` just like any other unauthenticated
request. After enough probes its own client key ends up blocked, and every
later probe gets 429, not 401. That's still definitive proof the gate is
actively enforcing (it's rejecting this probe, just via the rate limiter
instead of the credential check) -- treating it as unhealthy would flap a
correctly-gated instance to "unhealthy" purely from this check's own
polling. Only 200 (ungated) or a connection failure (ComfyUI not up) are
unhealthy.
"""

import sys
import urllib.error
import urllib.request

try:
    response = urllib.request.urlopen("http://localhost:8188/")
except urllib.error.HTTPError as exc:
    sys.exit(0 if exc.code in (401, 429) else 1)
else:
    # A 200 (or anything else that doesn't raise) means the gate did not
    # reject this unauthenticated request -- ungated, not healthy.
    response.close()
    sys.exit(1)
