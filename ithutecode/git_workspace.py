"""Local Git operations in a trusted, exclusive, disposable checkout.

No network, remote push, repository test execution or production access.
The caller must provision the checkout and discard it after any failure.
"""
import os
import re
import subprocess
from pathlib import Path
from .workspace import apply_edits
from .patch_policy import validate_edits

class GitWorkspace:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not (self.root / ".git").is_dir() or (self.root / ".git").is_symlink():
            raise ValueError("Standalone checkout required")

    def _git(self, *args):
        env = {"PATH": os.defpath, "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
               "GIT_LITERAL_PATHSPECS": "1"}
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull,
             "-c", "core.fsmonitor=false", "-c", "commit.gpgSign=false",
             "-c", "user.name=IthuteCode", "-c", "user.email=robot@ithutecode.invalid",
             *args], cwd=self.root, env=env, check=True, timeout=30,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def commit_edits(self, baseline, branch, edits, allowed_paths):
        if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40}", baseline):
            raise ValueError("Full baseline SHA required")
        if not isinstance(branch, str) or not re.fullmatch(r"ithutecode/[a-z0-9][a-z0-9-]{0,79}", branch):
            raise PermissionError("Dedicated development branch required")
        validate_edits(edits, allowed_paths)
        if self._git("rev-parse", "--show-toplevel").decode().strip() != str(self.root):
            raise ValueError("Unexpected checkout root")
        if self._git("rev-parse", "HEAD").decode().strip() != baseline:
            raise ValueError("Baseline commit mismatch")
        if self._git("symbolic-ref", "--short", "HEAD").decode().strip() != branch:
            raise PermissionError("Unexpected active branch")
        if self._git("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            raise ValueError("Workspace is not clean")
        for edit in edits:
            entry = self._git("ls-files", "--stage", "--", edit.path)
            if not entry.startswith((b"100644 ", b"100755 ")) or entry.count(b"\n") != 1:
                raise PermissionError("Expected tracked regular file")
            if self._git("check-attr", "filter", "--", edit.path).decode().strip().split(": ")[-1] not in {"unspecified", "unset"}:
                raise PermissionError("Git content filters are not supported")
        changed = apply_edits(self.root, edits, allowed_paths)
        self._git("add", "--", *changed)
        staged = self._git("diff", "--cached", "--name-only", "-z", "--no-renames")
        actual = set(staged.decode().rstrip("\0").split("\0"))
        if actual != set(changed):
            raise ValueError("Unexpected staged files")
        self._git("commit", "--no-verify", "-m", "IthuteCode: authorized source edits")
        commit = self._git("rev-parse", "HEAD").decode().strip()
        if self._git("rev-parse", "HEAD^").decode().strip() != baseline:
            raise RuntimeError("Unexpected commit parent")
        if self._git("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            raise RuntimeError("Unexpected changes after commit")
        return commit
