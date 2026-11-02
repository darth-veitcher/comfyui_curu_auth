"""The examples of README.md (docs/WRITING.md, rule 10).

Each fenced block of the README is either run here, or listed in
``NOT_RUN`` with the reason. A new block that is in neither place fails
``test_each_example_is_run_or_listed``, so no example goes unchecked by
accident.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()

#: A text that only one block holds -> why no test runs that block.
NOT_RUN = {
    "git clone https://github.com/darth-veitcher/comfyui_curu_auth": (
        "It needs the network and a ComfyUI install."
    ),
    "comfyui-curu-auth gate active. Credential:": (
        "Console output of a real ComfyUI start; the `system` tier sees it."
    ),
    "curl -H": (
        "It needs a running ComfyUI; the `system` tier covers the Bearer path."
    ),
    "authentication failure from 203.0.113.7": (
        "Log output; tests/test_gate.py and tests/test_oidc_providers.py check "
        "the format."
    ),
    "uv run pytest": "It runs this test suite itself.",
}

_SETTINGS_TEST = "test_each_setting_of_the_readme_is_read"
_CREDENTIAL_TEST = "test_the_credential_example_makes_a_credential"
_REDIRECT_URIS_TEST = "test_the_list_of_redirect_uris_gives_two_uris"

#: A text that only one block holds -> the test below that runs that block.
RUN = {
    "secrets.token_urlsafe(32)": _CREDENTIAL_TEST,
    "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL=": _SETTINGS_TEST,
    "COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS=": _SETTINGS_TEST,
    'COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI="http://': _REDIRECT_URIS_TEST,
}


def _blocks() -> list[str]:
    return re.findall(r"```[a-z]*\n(.*?)```", README, flags=re.DOTALL)


def test_each_example_is_run_or_listed() -> None:
    for block in _blocks():
        known = [text for text in (*NOT_RUN, *RUN) if text in block]
        assert known, f"README example with no test and no reason:\n{block}"


def test_the_credential_example_makes_a_credential() -> None:
    match = re.search(r"python3 -c '([^']+)'", README)
    assert match is not None
    result = subprocess.run(
        [sys.executable, "-c", match.group(1)],
        capture_output=True,
        text=True,
        check=True,
    )
    # token_urlsafe(32): 32 bytes in base64url with no padding.
    assert len(result.stdout.strip()) == 43


def test_the_list_of_redirect_uris_gives_two_uris() -> None:
    """The example of more than one address passes the setting check, and
    its first URL is the default."""
    from oidc import resolve_oidc_config

    match = re.search(r'COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI="(http://[^"]+)"', README)
    assert match is not None
    config = resolve_oidc_config(
        issuer_url="https://idp.example.com/",
        client_id="client",
        client_secret="secret",
        redirect_uri=match.group(1),
        allow_any_user="true",
    )

    assert config is not None
    assert len(config.redirect_uris) == 2
    assert config.redirect_uri == match.group(1).split(",")[0]


def test_each_setting_of_the_readme_is_read() -> None:
    """Each COMFYUI_CURU_AUTH_ name of the README is read by __init__.py, and
    each name that __init__.py reads is in the README."""
    pattern = r"COMFYUI_CURU_AUTH_[A-Z_]*[A-Z]"
    init = (ROOT / "__init__.py").read_text()
    in_readme = set(re.findall(pattern, README)) - {"COMFYUI_CURU_AUTH_OIDC"}
    read_by_init = set(re.findall(rf'os\.environ\.get\(\s*"({pattern})"', init))

    assert in_readme == read_by_init
