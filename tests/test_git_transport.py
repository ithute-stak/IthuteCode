import subprocess
import tempfile
import unittest
from pathlib import Path
from ithutecode.git_transport import GitTransport

class GitTransportTests(unittest.TestCase):
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
        self.baseline = self.commit("first")
        self.git(self.local, "push", str(self.remote), "HEAD:refs/heads/ithutecode/demo")
        self.candidate = self.commit("second")
        self.transport = GitTransport(self.local, 42, self.remote, local_test=True)

    def git(self, cwd, *args):
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.PIPE, text=True).strip()

    def commit(self, content):
        (self.local / "app.py").write_text(content)
        self.git(self.local, "add", "app.py")
        self.git(self.local, "commit", "-m", content)
        return self.git(self.local, "rev-parse", "HEAD")

    def remote_sha(self):
        return self.git(self.remote, "rev-parse", "refs/heads/ithutecode/demo")

    def test_real_push(self):
        self.assertEqual(self.transport.publish(42,"ithutecode/demo",self.baseline,self.candidate),self.candidate)
        self.assertEqual(self.remote_sha(),self.candidate)

    def test_stale_lease(self):
        self.git(self.remote,"update-ref","refs/heads/ithutecode/demo",self.baseline)
        other = self.commit("third")
        # Transfer the competing commit, then restore local candidate.
        self.git(self.local,"push",str(self.remote),"HEAD:refs/heads/ithutecode/demo")
        self.git(self.local,"reset","--hard",self.candidate)
        with self.assertRaises(subprocess.CalledProcessError):
            self.transport.publish(42,"ithutecode/demo",self.baseline,self.candidate)
        self.assertEqual(self.remote_sha(),other)

    def test_wrong_repository(self):
        with self.assertRaises(PermissionError):
            self.transport.publish(43,"ithutecode/demo",self.baseline,self.candidate)
        self.assertEqual(self.remote_sha(),self.baseline)

    def test_protected_branch(self):
        with self.assertRaises(PermissionError):
            self.transport.publish(42,"main",self.baseline,self.candidate)

    def test_wrong_parent(self):
        with self.assertRaises(ValueError):
            self.transport.publish(42,"ithutecode/demo","0"*40,self.candidate)

    def test_noncanonical_remote(self):
        with self.assertRaises(ValueError):
            GitTransport(self.local,42,"https://example.org/repo.git")
