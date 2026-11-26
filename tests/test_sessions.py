import json
import tempfile
import unittest
from pathlib import Path
from ithutecode.store import ProjectStore
from ithutecode.checkpoints import Checkpoints
from ithutecode.sessions import SessionManager
from ithutecode.agent import CodingAgent, CodingRequest

class SessionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/"state.db"
        self.store = ProjectStore(self.path)
        self.store.create_project("p","owner/repo","Build securely",["First","Second"])
        self.sha = "a"*40
        self.store.record_candidate("p",0,self.sha)
        self.checkpoints = Checkpoints(self.store)
        self.checkpoints.save("p",self.sha,"Historical note",self.verify)
        self.calls = []
        self.fail_provider = False

    def verify(self,project,sha):
        return project=="p" and sha==self.sha

    def propose(self,instructions,payload,max_output_tokens):
        self.calls.append(json.loads(payload))
        if self.fail_provider:
            raise OSError("uncertain provider result")
        return '{"edits":[]}'

    def manager(self,limit=10000,counter=None):
        return SessionManager(Checkpoints(ProjectStore(self.path)),self,self.verify,
            counter or (lambda instructions,payload:len(instructions)+len(payload)),
            limit,overhead_tokens=100)

    def request(self,manager,requirement="First",context="source"):
        return CodingAgent(manager,max_output_tokens=100).propose(
            CodingRequest("p",requirement,self.sha,"implement",context))

    def test_fresh_sessions_recover_after_restart(self):
        self.request(self.manager())
        self.request(self.manager())
        self.assertEqual(len(self.calls),2)
        for call in self.calls:
            self.assertEqual(call["project_memory"]["original_instruction"],"Build securely")
            self.assertEqual(call["project_memory"]["untrusted_checkpoint_notes"],"Historical note")
        history=self.manager().history("p")
        self.assertEqual(len(history),2)
        self.assertNotEqual(history[0]["id"],history[1]["id"])
        self.assertEqual([h["status"] for h in history],["completed","completed"])

    def test_next_task_context_reconstructed(self):
        self.request(self.manager())
        self.store.accept("p",0,self.sha,"Verified")
        self.request(self.manager(),"Second")
        memory=self.calls[-1]["project_memory"]
        self.assertEqual(memory["active_ordinal"],1)
        self.assertEqual(memory["verified_tasks"],[0])
        self.assertEqual(memory["untrusted_checkpoint_notes"],"")

    def test_optional_notes_removed_when_context_tight(self):
        counter=lambda instructions,payload: 950 if "Historical note" in payload else 500
        self.request(self.manager(1000,counter))
        self.assertEqual(self.calls[-1]["project_memory"]["untrusted_checkpoint_notes"],"")

    def test_mandatory_context_never_silently_truncated(self):
        with self.assertRaises(ValueError):
            self.request(self.manager(1000,lambda *args:1000))
        self.assertEqual(self.calls,[])

    def test_uncertain_provider_blocks_restart_replay(self):
        self.fail_provider=True
        with self.assertRaises(OSError):
            self.request(self.manager())
        self.fail_provider=False
        with self.assertRaises(RuntimeError):
            self.request(self.manager())
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.manager().history("p")[0]["status"],"uncertain")

    def test_paused_project(self):
        self.store.set_paused("p",True)
        with self.assertRaises(PermissionError):
            self.request(self.manager())
        self.assertEqual(self.calls,[])

    def test_wrong_requirement(self):
        with self.assertRaises(PermissionError):
            self.request(self.manager(),"Unauthorized")
        self.assertEqual(self.calls,[])

    def test_stale_head(self):
        self.sha="b"*40
        with self.assertRaises(PermissionError):
            self.request(self.manager())
        self.assertEqual(self.calls,[])
