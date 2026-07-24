FROM python:3.13-slim

WORKDIR /app

# Install system deps needed by ComfyUI
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libgl1 \
    libglib2.0-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Trusts the harness's own, repo-committed Authelia CA (spec 002,
# research.md) at the OS level -- NOT a TLS-verification bypass in
# oidc.py itself. The exact same discovery/token/JWKS-fetch code that
# will run against a real, publicly-trusted provider in production runs
# unmodified here; only the OS trust store differs, and only in this
# disposable image.
COPY docker/authelia/ca.crt /usr/local/share/ca-certificates/authelia-local-harness-ca.crt
RUN update-ca-certificates

# Clone ComfyUI (pinned tag for reproducibility; bump manually) -- same tag
# already validated by the sibling repo's own harness
# (~/repos/JAMESVEITCH/curu), removing a variable (research.md).
ARG COMFYUI_VERSION=v0.27.0
RUN git clone --depth 1 --branch ${COMFYUI_VERSION} \
    https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI

WORKDIR /app/ComfyUI

# Install ComfyUI deps with CPU-only torch (no CUDA download)
# requests is imported by app/frontend_management.py but not listed in
# ComfyUI's requirements.txt at this tag -- pin it explicitly (same footgun
# curu's own Dockerfile already documents at this exact tag).
RUN pip install --no-cache-dir \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir requests

# joserfc: comfyui_curu_auth's own OIDC ID-token verification dependency
# (spec 002, research.md) -- not a ComfyUI dependency, so it isn't
# installed by the requirements.txt step above. aiohttp is already
# installed by that step (a ComfyUI dependency too), so no separate
# install is needed for it.
RUN pip install --no-cache-dir "joserfc>=1.0"

# comfyui_curu_auth is NOT copied or cloned into this image -- unlike
# curu's own harness (which installs a published release), this harness's
# entire purpose is testing this repo's own in-progress working tree
# (spec FR-002). docker-compose.yml bind-mounts the repo root read-only to
# custom_nodes/comfyui_curu_auth at container-start time instead, so a
# plain restart (no rebuild) picks up local edits (research.md).

EXPOSE 8188

# Requires 401 specifically -- NOT curu's own tolerant version, which
# treats 200 as healthy too. That's safe for curu (node baked into the
# image, always present) but wrong here: this harness's entire premise is
# a bind mount that can fail, in which case ComfyUI comes up ungated and
# answers 200. See healthcheck.py and research.md's healthcheck decision.
COPY docker/comfyui/healthcheck.py healthcheck.py
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=12 \
    CMD python healthcheck.py

# NOTE: --quick-test-for-ci is deliberately NOT passed -- in ComfyUI's own
# main.py that flag exits immediately after routes are registered but
# before the HTTP server actually starts listening (verified against
# curu's own Dockerfile comment on this exact point). This harness needs a
# persistent server for the whole test lifecycle.
CMD ["python", "main.py", "--cpu", "--listen", "0.0.0.0", "--port", "8188"]
