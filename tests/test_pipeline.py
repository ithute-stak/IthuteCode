import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from ithutecode.agent import CodingAgent, CodingRequest
from ithutecode.pipeline import CodingPipeline, CodingJob

class PipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.git("init", "-b", "ithutecode/demo")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgSign", "false")
        (self.root/"app.py").write_text("value = 1\n")
        self.git("add", "app.py")
        self.git("commit", "-m", "baseline")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.job = CodingJob(CodingRequest("project","Change value",self.sha,"implement"),
                             "ithutecode/demo",frozenset({"app.py"}))
        self.calls = 0
        self.bad = False

    def git(self,*args):
        return subprocess.check_output(["git",*args],cwd=self.root,stderr=subprocess.PIPE,text=True)

    def propose(self,instructions,payload,max_output_tokens):
        self.calls += 1
        source = json.loads(json.loads(payload)["repository_context"])["authorized_files"][0]
        return json.dumps({"edits":[{"path":"other.py" if self.bad else source["path"],
            "expected_sha256":source["expected_sha256"],"content":"value = 2\n"}]})

    def test_integrated_commit(self):
        result = CodingPipeline(CodingAgent(self),lambda job:True).run(self.root,self.job)
        self.assertEqual(result.baseline_sha,self.sha)
        self.assertEqual(result.commit_sha,self.git("rev-parse","HEAD").strip())
        self.assertEqual(self.git("show","HEAD:app.py"),"value = 2\n")
        self.assertEqual(self.calls,1)

    def test_denied_before_ai(self):
        with self.assertRaises(PermissionError):
            CodingPipeline(CodingAgent(self),lambda job:False).run(self.root,self.job)
        self.assertEqual(self.calls,0)

    def test_revoked_after_ai(self):
        with self.assertRaises(PermissionError):
            CodingPipeline(CodingAgent(self),lambda job:self.calls==0).run(self.root,self.job)
        self.assertEqual(self.git("rev-parse","HEAD").strip(),self.sha)
        self.assertEqual((self.root/"app.py").read_text(),"value = 1\n")

    def test_unauthorized_proposal(self):
        self.bad = True
        with self.assertRaises(PermissionError):
            CodingPipeline(CodingAgent(self),lambda job:True).run(self.root,self.job)
        self.assertEqual(self.git("rev-parse","HEAD").strip(),self.sha)

    def test_dirty_checkout_rejected_before_ai(self):
        (self.root/"app.py").write_text("dirty")
        with self.assertRaises(ValueError):
            CodingPipeline(CodingAgent(self),lambda job:True).run(self.root,self.job)
        self.assertEqual(self.calls,0)
