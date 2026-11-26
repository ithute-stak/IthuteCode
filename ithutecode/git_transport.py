"""Git transport for trusted disposable checkouts and explicitly mapped remotes.

The remote mapping and credential environment must be supplied by trusted
infrastructure. Never derive them from model output or repository contents.
"""
import os
import re
import subprocess
from pathlib import Path
from .git_credentials import credential_environment

class GitTransport:
    def __init__(self, root, repository_id, remote, *, local_test=False, token_provider=None):
        self.root = Path(root).resolve(strict=True)
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("Invalid repository identity")
        if not (self.root / ".git").is_dir() or (self.root / ".git").is_symlink():
            raise ValueError("Standalone checkout required")
        self.repository_id = repository_id
        if local_test and token_provider is not None:
            raise ValueError("Credentials forbidden for local remotes")
        self.token_provider = token_provider
        if local_test:
            self.remote = str(Path(remote).resolve(strict=True))
            self.protocol = "file"
        else:
            if not isinstance(remote, str) or not re.fullmatch(
                r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", remote
            ):
                raise ValueError("Expected canonical GitHub HTTPS URL")
            self.remote = remote
            self.protocol = "https"

    def _git(self, *args):
        env = {"PATH": os.defpath, "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
               "GIT_ALLOW_PROTOCOL": self.protocol}
        if self.token_provider is not None and args[0] in {"push", "ls-remote"}:
            env.update(credential_environment(self.repository_id, self.remote, self.token_provider))
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull,
             "-c", "core.fsmonitor=false", "-c", "http.followRedirects=false",
             *args], cwd=self.root, env=env, check=True, timeout=60,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def publish(self, repository_id, branch, expected_sha, commit_sha):
        if repository_id != self.repository_id:
            raise PermissionError("Repository identity mismatch")
        if not isinstance(branch, str) or not re.fullmatch(
            r"ithutecode/[a-z0-9][a-z0-9-]{0,79}", branch
        ):
            raise PermissionError("Dedicated development branch required")
        for sha in (expected_sha, commit_sha):
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("Invalid commit SHA")
        if self._git("rev-parse", "HEAD") != commit_sha:
            raise ValueError("Commit must be checkout HEAD")
        if self._git("symbolic-ref", "--short", "HEAD") != branch:
            raise PermissionError("Unexpected local branch")
        if self._git("rev-list", "--parents", "-n", "1", commit_sha).split() != [commit_sha, expected_sha]:
            raise ValueError("Expected exactly one direct parent")
        ref = "refs/heads/" + branch
        # The explicit lease checks the remote baseline atomically. The parent
        # check above ensures this cannot intentionally rewrite branch history.
        self._git("push", "--no-follow-tags", "--force-with-lease=" + ref + ":" + expected_sha,
                  "--", self.remote, commit_sha + ":" + ref)
        observed = self._git("ls-remote", "--refs", "--", self.remote, ref)
        if observed.split() != [commit_sha, ref]:
            raise RuntimeError("Remote publication uncertain")
        return commit_sha

    def initialize_branch(self, repository_id, branch, baseline_sha, authorize):
        """Create only an absent development ref; resume only at exact baseline."""
        if type(repository_id) is not int or repository_id != self.repository_id:
            raise PermissionError("Repository identity mismatch")
        if not isinstance(branch, str) or not re.fullmatch(
            r"ithutecode/[a-z0-9][a-z0-9-]{0,79}", branch
        ):
            raise PermissionError("Dedicated development branch required")
        if not isinstance(baseline_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", baseline_sha):
            raise ValueError("Invalid baseline SHA")
        if not authorize(repository_id, branch, baseline_sha):
            raise PermissionError("Branch initialization not authorized")
        if self._git("rev-parse", "HEAD") != baseline_sha:
            raise ValueError("Checkout baseline mismatch")
        if self._git("symbolic-ref", "--short", "HEAD") != branch:
            raise PermissionError("Unexpected local branch")
        ref = "refs/heads/" + branch
        observed = self._git("ls-remote", "--refs", "--", self.remote, ref)
        if observed:
            if observed.split() == [baseline_sha, ref]:
                return baseline_sha
            raise RuntimeError("Remote branch already exists at another commit")
        if not authorize(repository_id, branch, baseline_sha):
            raise PermissionError("Branch initialization authorization withdrawn")
        self._git("push", "--no-follow-tags", "--force-with-lease=" + ref + ":",
                  "--", self.remote, baseline_sha + ":" + ref)
        observed = self._git("ls-remote", "--refs", "--", self.remote, ref)
        if observed.split() != [baseline_sha, ref]:
            raise RuntimeError("Branch initialization uncertain; reconcile before retry")
        return baseline_sha
