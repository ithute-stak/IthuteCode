import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from ithutecode.git_workspace import GitWorkspace
from ithutecode.patch_policy import Edit

class GitWorkspaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.git("init", "-b", "ithutecode/demo")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgSign", "false")
        (self.root / "app.py").write_text("old\n")
        self.git("add", "app.py")
        self.git("commit", "-m", "baseline")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.edit = Edit("app.py", hashlib.sha256(b"old\n").hexdigest(), "new\n")
        self.allowed = frozenset({"app.py"})
        self.workspace = GitWorkspace(self.root)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE, text=True)

    def commit(self, baseline=None, branch="ithutecode/demo"):
        return self.workspace.commit_edits(baseline or self.sha, branch, (self.edit,), self.allowed)

    def test_commit_exact_changes(self):
        result = self.commit()
        self.assertNotEqual(result, self.sha)
        self.assertEqual(self.git("rev-parse", "HEAD^").strip(), self.sha)
        self.assertEqual(self.git("show", "--format=", "--name-only", result).strip(), "app.py")
        self.assertEqual(self.git("show", "HEAD:app.py"), "new\n")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_wrong_baseline(self):
        with self.assertRaises(ValueError):
            self.commit("0"*40)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.sha)

    def test_protected_branch(self):
        with self.assertRaises(PermissionError):
            self.commit(branch="main")

    def test_wrong_active_branch(self):
        with self.assertRaises(PermissionError):
            self.commit(branch="ithutecode/other")

    def test_dirty_workspace(self):
        (self.root/"unexpected.txt").write_text("dirty")
        with self.assertRaises(ValueError):
            self.commit()
        self.assertEqual((self.root/"app.py").read_text(), "old\n")

    def test_stale_content_hash(self):
        edit = Edit("app.py","0"*64,"new")
        with self.assertRaises(ValueError):
            self.workspace.commit_edits(self.sha,"ithutecode/demo",(edit,),self.allowed)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.sha)
