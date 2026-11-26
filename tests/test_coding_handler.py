import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from ithutecode.agent import CodingAgent, CodingRequest
from ithutecode.pipeline import CodingJob
from ithutecode.coding_handler import CodingHandler, CodingPlan

class CodingHandlerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.remote = self.root / "remote.git"
        self.source = self.root / "source"
        self.source.mkdir()
        self.workspaces = self.root / "workspaces"
        self.workspaces.mkdir()
        self.git(self.root,"init","--bare",str(self.remote))
        self.git(self.source,"init","-b","main")
        self.git(self.source,"config","user.name","Test")
        self.git(self.source,"config","user.email","test@example.invalid")
        self.git(self.source,"config","commit.gpgSign","false")
        (self.source/"app.py").write_text("value = 1\n")
        self.git(self.source,"add","app.py")
        self.git(self.source,"commit","-m","baseline")
        self.sha = self.git(self.source,"rev-parse","HEAD")
        self.git(self.source,"push",str(self.remote),"HEAD:refs/heads/main")
        self.branch = "ithutecode/demo"
        self.plan = CodingPlan(42,str(self.remote),CodingJob(
            CodingRequest("project","Change value",self.sha,"implement"),self.branch,
            frozenset({"app.py"})))
        self.claimed = {"id":"job","project_id":"project","payload":{"decision":{
            "project_id":"project","decision":"next_task","sha":self.sha}}}
        self.events = []
        self.allow = True
        self.verify = True

    def git(self,cwd,*args):
        return subprocess.check_output(["git",*args],cwd=cwd,stderr=subprocess.PIPE,text=True).strip()

    def guard(self):
        if not self.allow:
            raise PermissionError("revoked")

    def propose(self,instructions,payload,max_output_tokens):
        self.events.append("ai")
        source = json.loads(json.loads(payload)["repository_context"])["authorized_files"][0]
        return json.dumps({"edits":[{"path":source["path"],"expected_sha256":source["expected_sha256"],"content":"value = 2\n"}]})

    def record_intent(self,claimed,publication):
        self.events.append("intent")

    def record_published(self,claimed,publication):
        self.events.append("published")

    def handler(self):
        return CodingHandler(self.workspaces,CodingAgent(self),lambda _:self.plan,
            lambda _:self.events.append("budget"),lambda *args:self.verify,self,local_test=True)

    def test_integrated_local_publication(self):
        result = self.handler()(self.claimed,self.guard)
        self.assertEqual(self.git(self.remote,"rev-parse","refs/heads/"+self.branch),result["commit_sha"])
        self.assertEqual(self.git(self.remote,"show",result["commit_sha"]+":app.py"),"value = 2")
        self.assertEqual(self.git(self.remote,"rev-parse","refs/heads/main"),self.sha)
        self.assertEqual(self.events,["budget","ai","intent","published"])
        self.assertEqual(list(self.workspaces.iterdir()),[])

    def test_revoked_before_execution(self):
        self.allow = False
        with self.assertRaises(PermissionError):
            self.handler()(self.claimed,self.guard)
        self.assertEqual(self.events,[])

    def test_stale_plan(self):
        self.claimed["payload"]["decision"]["sha"] = "0"*40
        with self.assertRaises(PermissionError):
            self.handler()(self.claimed,self.guard)
        self.assertEqual(self.events,[])

    def test_unverified_commit_not_published(self):
        self.verify = False
        with self.assertRaises(PermissionError):
            self.handler()(self.claimed,self.guard)
        self.assertEqual(self.git(self.remote,"rev-parse","refs/heads/"+self.branch),self.sha)
        self.assertEqual(self.events,["budget","ai","intent"])
