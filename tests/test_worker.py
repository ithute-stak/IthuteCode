import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from ithutecode.engine import Snapshot
from ithutecode.ci import RequiredCheck
from ithutecode.github_events import Inbox, Notice
from ithutecode.worker import Worker, Target, DecisionOutbox

SHA = "a" * 40

class WorkerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "state.db"
        self.inbox = Inbox(path)
        self.outbox = DecisionOutbox(path)
        self.target = Target("project",42,0,Snapshot(SHA,"",("tests",),{}),
                             (RequiredCheck("tests",12),))
        self.status = "success"
        self.error = False
        self.calls = 0
        self.worker = Worker(self.inbox,self.outbox,self,lambda repo,sha:[self.target])

    def required_statuses(self, repo, sha, required):
        self.calls += 1
        if self.error:
            raise OSError("offline")
        return {"tests":self.status}

    def enqueue(self, delivery="one"):
        self.inbox.enqueue(delivery,Notice(42,SHA))

    def test_green_requires_review(self):
        self.enqueue()
        self.assertEqual(self.worker.run_once(),{"processed":1,"failed":0})
        self.assertEqual(self.outbox.entries()[0][3],"review")
        self.assertEqual(self.inbox.pending(),[])

    def test_replay_does_not_duplicate(self):
        self.enqueue()
        self.worker.run_once()
        self.enqueue("two")
        self.worker.run_once()
        self.assertEqual(len(self.outbox.entries()),1)

    def test_api_failure_retries(self):
        self.enqueue()
        self.error = True
        self.assertEqual(self.worker.run_once()["failed"],1)
        self.assertEqual(len(self.inbox.pending()),1)
        self.error = False
        self.worker.run_once()
        self.assertEqual(len(self.outbox.entries()),1)

    def test_stale_target_ignored(self):
        self.target = replace(self.target,snapshot=replace(self.target.snapshot,candidate_sha="b"*40))
        self.enqueue()
        self.worker.run_once()
        self.assertEqual(self.calls,0)
        self.assertEqual(self.outbox.entries(),[])

    def test_failure_requests_repair(self):
        self.status = "failure"
        self.enqueue()
        self.worker.run_once()
        self.assertEqual(self.outbox.entries()[0][3],"repair")

    def test_pending_creates_no_action(self):
        self.status = "pending"
        self.enqueue()
        self.worker.run_once()
        self.assertEqual(self.outbox.entries(),[])

    def test_paused_creates_no_action(self):
        self.target = replace(self.target,snapshot=replace(self.target.snapshot,paused=True))
        self.enqueue()
        self.worker.run_once()
        self.assertEqual(self.calls,0)
        self.assertEqual(self.outbox.entries(),[])

    def test_policy_mismatch_fails_closed(self):
        self.target = replace(self.target,required=(RequiredCheck("other",12),))
        self.enqueue()
        self.assertEqual(self.worker.run_once()["failed"],1)
        self.assertEqual(self.outbox.entries(),[])
