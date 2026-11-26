import subprocess
import tempfile
import unittest
from pathlib import Path
from ithutecode.provision import provision

class ProvisionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.git(self.source, "init", "-b", "main")
        self.git(self.source, "config", "user.name", "Test")
        self.git(self.source, "config", "user.email", "test@example.invalid")
        self.git(self.source, "config", "commit.gpgSign", "false")
        (self.source / "app.py").write_text("value = 1\n")
        self.git(self.source, "add", "app.py")
        self.git(self.source, "commit", "-m", "baseline")
        self.sha = self.git(self.source, "rev-parse", "HEAD")
        self.parent = self.root / "workspaces"
        self.parent.mkdir()

    def git(self, cwd, *args):
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.PIPE, text=True).strip()

    def checkout(self, sha=None, branch="ithutecode/demo"):
        return provision(self.parent, self.source, sha or self.sha, branch, local_test=True)

    def test_exact_checkout_and_cleanup(self):
        with self.checkout() as workspace:
            self.assertEqual(self.git(workspace, "rev-parse", "HEAD"), self.sha)
            self.assertEqual(self.git(workspace, "branch", "--show-current"), "ithutecode/demo")
            self.assertEqual((workspace / "app.py").read_text(), "value = 1\n")
        self.assertFalse(workspace.exists())

    def test_cleanup_on_failure(self):
        with self.assertRaises(RuntimeError):
            with self.checkout() as workspace:
                raise RuntimeError("failed task")
        self.assertFalse(workspace.exists())

    def test_protected_branch(self):
        with self.assertRaises(PermissionError):
            with self.checkout(branch="main"):
                self.fail("unexpected checkout")

    def test_invalid_sha(self):
        with self.assertRaises(ValueError):
            with self.checkout(sha="HEAD"):
                self.fail("unexpected checkout")

    def test_symlink_rejected_before_checkout(self):
        (self.source / "link.py").symlink_to("app.py")
        self.git(self.source, "add", "link.py")
        self.git(self.source, "commit", "-m", "symlink")
        sha = self.git(self.source, "rev-parse", "HEAD")
        with self.assertRaises(PermissionError):
            with self.checkout(sha=sha):
                self.fail("unexpected checkout")
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_noncanonical_remote(self):
        with self.assertRaises(ValueError):
            with provision(self.parent, "https://example.org/test.git", self.sha, "ithutecode/demo"):
                self.fail("unexpected checkout")
