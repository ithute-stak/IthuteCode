import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from ithutecode.store import ProjectStore
from ithutecode.checkpoints import Checkpoints
from ithutecode.sessions import SessionManager
from ithutecode.session_recovery import SessionRecovery, SessionEvidence
from ithutecode.agent import CodingAgent, CodingRequest

class SessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ProjectStore(Path(tmp.name)/"state.db")
        self.store.create_project("p","owner/repo","Build",["First"])
        self.sha = "a"*40
        self.store.record_candidate("p",0,self.sha)
        self.sessions = SessionManager(Checkpoints(self.store),self,lambda *args:True,
            lambda *args:100,10000)
        self.agent = CodingAgent(self.sessions)
        self.fail = True
        self.auth = True
        self.stopped = True
        with self.assertRaises(OSError):
            self.request()
        row = self.sessions.history("p")[0]
        self.evidence = SessionEvidence(row["id"],"p",row["request_digest"],
            "provider-ref","failed",100,10,20)
        self.recovery = SessionRecovery(self.sessions,lambda e:self.auth,lambda s:self.stopped)

    def propose(self,*args):
        if self.fail:
            raise OSError("uncertain")
        return '{"edits":[]}'

    def request(self):
        return self.agent.propose(CodingRequest("p","First",self.sha,"implement"))

    def test_reconcile_and_fresh_request(self):
        self.assertEqual(self.recovery.reconcile(self.evidence),"reconciled")
        self.fail=False
        self.request()
        self.assertEqual([r["status"] for r in self.sessions.history("p")],
                         ["reconciled","completed"])

    def test_idempotent_reconciliation(self):
        self.recovery.reconcile(self.evidence)
        self.assertEqual(self.recovery.reconcile(self.evidence),"reconciled")
        with self.assertRaises(PermissionError):
            self.recovery.reconcile(replace(self.evidence,actual_units=21))

    def test_identity_mismatch(self):
        for e in (replace(self.evidence,project_id="other"),
                  replace(self.evidence,request_digest="bad")):
            with self.assertRaises(PermissionError):
                self.recovery.reconcile(e)

    def test_requires_fenced_worker(self):
        self.stopped=False
        with self.assertRaises(PermissionError):
            self.recovery.reconcile(self.evidence)

    def test_requires_authenticated_evidence(self):
        self.auth=False
        with self.assertRaises(PermissionError):
            self.recovery.reconcile(self.evidence)
        with self.assertRaises(RuntimeError):
            self.request()

    def test_invalid_usage(self):
        for e in (replace(self.evidence,actual_units=-1),
                  replace(self.evidence,outcome="not_submitted"),
                  replace(self.evidence,outcome="unknown")):
            with self.assertRaises(ValueError):
                self.recovery.reconcile(e)

    def test_crash_before_error_recording(self):
        with self.store.transaction() as db:
            db.execute("UPDATE ai_sessions SET status='started'")
        self.assertEqual(self.recovery.reconcile(self.evidence),"reconciled")

    def test_provider_reference_cannot_be_reused(self):
        self.recovery.reconcile(self.evidence)
        with self.assertRaises(OSError):
            self.request()
        row=self.sessions.history("p")[-1]
        with self.assertRaises(PermissionError):
            self.recovery.reconcile(replace(self.evidence,session_id=row["id"],
                request_digest=row["request_digest"]))
