import subprocess
import tempfile
import unittest
from pathlib import Path
from ithutecode.git_transport import GitTransport

class BranchInitializationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.remote = root / "remote.git"
        self.local = root / "local"
        self.local.mkdir()
        self.git(root, "init", "--bare", str(self.remote))
        self.git(self.local, "init", "-b", "ithutecode/demo")
        self.git(self.local, "config", "user.name", "Test")
        self.git(self.local, "config", "user.email", "test@example.invalid")
        self.git(self.local, "config", "commit.gpgSign", "false")
        self.git(self.local, "commit", "--allow-empty", "-m", "baseline")
        self.sha = self.git(self.local, "rev-parse", "HEAD")
        self.transport = GitTransport(self.local, 42, self.remote, local_test=True)

    def git(self, cwd, *args):
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.PIPE, text=True).strip()

    def initialize(self, authorize=lambda *args: True):
        return self.transport.initialize_branch(42, "ithutecode/demo", self.sha, authorize)

    def remote_sha(self):
        return self.git(self.remote, "rev-parse", "refs/heads/ithutecode/demo")

    def test_create_and_resume(self):
        self.assertEqual(self.initialize(), self.sha)
        self.assertEqual(self.initialize(), self.sha)
        self.assertEqual(self.remote_sha(), self.sha)

    def test_existing_other_commit_not_overwritten(self):
        self.initialize()
        self.git(self.local, "commit", "--allow-empty", "-m", "other")
        other = self.git(self.local, "rev-parse", "HEAD")
        self.git(self.local, "push", str(self.remote), "HEAD:refs/heads/ithutecode/demo")
        self.git(self.local, "reset", "--hard", self.sha)
        with self.assertRaises(RuntimeError):
            self.initialize()
        self.assertEqual(self.remote_sha(), other)

    def test_denied(self):
        with self.assertRaises(PermissionError):
            self.initialize(lambda *args: False)
        self.assertEqual(self.git(self.remote, "for-each-ref"), "")

    def test_revoked_before_push(self):
        checks = iter([True, False])
        with self.assertRaises(PermissionError):
            self.initialize(lambda *args: next(checks))
        self.assertEqual(self.git(self.remote, "for-each-ref"), "")

    def test_protected_branch(self):
        with self.assertRaises(PermissionError):
            self.transport.initialize_branch(42, "main", self.sha, lambda *args: True)

    def test_wrong_repository(self):
        with self.assertRaises(PermissionError):
            self.transport.initialize_branch(43, "ithutecode/demo", self.sha, lambda *args: True)
