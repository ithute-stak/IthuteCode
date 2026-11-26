"""Provision trusted disposable checkouts without executing repository code.

HTTPS mode optionally accepts a trusted repository-scoped token provider. The workspace parent and repository mapping must be trusted.
"""
from contextlib import contextmanager
from pathlib import Path
import os
import re
import subprocess
import tempfile
from .git_credentials import credential_environment

def _git(root, protocol, *args, auth=None):
    env = {"PATH": os.defpath, "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
           "GIT_ALLOW_PROTOCOL": protocol}
    if auth is not None:
        env.update(auth)
    return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
        "-c", "core.fsmonitor=false", "-c", "http.followRedirects=false",
        *args], cwd=root, env=env, check=True, timeout=60,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

@contextmanager
def provision(parent, remote, baseline, branch, *, local_test=False, repository_id=None, token_provider=None):
    if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise ValueError("Full baseline SHA required")
    if not isinstance(branch, str) or not re.fullmatch(r"ithutecode/[a-z0-9][a-z0-9-]{0,79}", branch):
        raise PermissionError("Dedicated development branch required")
    parent = Path(parent).resolve(strict=True)
    if local_test and token_provider is not None:
        raise ValueError("Credentials forbidden for local remotes")
    if local_test:
        remote = str(Path(remote).resolve(strict=True))
        protocol = "file"
    else:
        if not isinstance(remote, str) or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", remote):
            raise ValueError("Canonical HTTPS GitHub remote required")
        protocol = "https"
    with tempfile.TemporaryDirectory(prefix="ithutecode-", dir=parent) as directory:
        root = Path(directory)
        _git(root, protocol, "init", "--template=")
        auth = credential_environment(repository_id, remote, token_provider) if token_provider is not None else None
        _git(root, protocol, "fetch", "--no-tags", "--depth=1", "--", remote, baseline, auth=auth)
        del auth
        if _git(root, protocol, "rev-parse", "FETCH_HEAD") != baseline:
            raise RuntimeError("Fetched baseline mismatch")
        # Reject symlinks and submodules before checking out the tree.
        tree = _git(root, protocol, "ls-tree", "-r", "-z", baseline)
        for entry in tree.split("\0"):
            if entry and not entry.startswith(("100644 blob ", "100755 blob ")):
                raise PermissionError("Unsupported tree entry")
        _git(root, protocol, "switch", "-c", branch, baseline)
        if _git(root, protocol, "rev-parse", "HEAD") != baseline:
            raise RuntimeError("Checkout baseline mismatch")
        if _git(root, protocol, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("Checkout not clean")
        yield root
