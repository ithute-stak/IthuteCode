"""Runtime-only authentication for trusted Git subprocesses.

The provider must issue a repository-scoped installation token. Never pass
this environment to repository code or AI workers.
"""
import base64
import re

def credential_environment(repository_id, remote, token_provider):
    if type(repository_id) is not int or repository_id <= 0:
        raise ValueError("Invalid repository identity")
    if not isinstance(remote, str) or not re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", remote
    ):
        raise ValueError("Canonical GitHub remote required")
    token = token_provider(repository_id)
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,2048}", token):
        raise ValueError("Invalid credential")
    encoded = base64.b64encode(("x-access-token:" + token).encode("ascii")).decode("ascii")
    return {
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_0": "http." + remote + ".extraHeader",
        "GIT_CONFIG_VALUE_0": "Authorization: Basic " + encoded,
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": "",
        "GIT_CONFIG_KEY_2": "http.followRedirects",
        "GIT_CONFIG_VALUE_2": "false",
    }
