import tempfile
import unittest
from pathlib import Path
from ithutecode.jobs import JobQueue
from ithutecode.worker import DecisionOutbox, Target
from ithutecode.engine import Snapshot, Decision
from ithutecode.ci import RequiredCheck
from ithutecode.dispatch import Dispatcher

class DispatcherTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/"db"
        self.queue = JobQueue(self.path)
        self.outbox = DecisionOutbox(self.path)
        self.target = Target("project",42,0,Snapshot("a"*40,"a"*40,("tests",),{"tests":"success"}),(RequiredCheck("tests",12),))
        self.outbox.record(self.target,Decision.REVIEW,{"tests":"success"})

    def test_dispatch_and_claim(self):
        dispatcher = Dispatcher(self.queue,lambda d:{"kind":d.decision})
        self.assertEqual(dispatcher.run_once(),{"dispatched":1,"deferred":0})
        job = self.queue.claim()
        self.assertEqual(job["payload"]["job"],{"kind":"review"})
        self.assertEqual(job["payload"]["decision"]["sha"],"a"*40)
        self.assertEqual(job["project_id"],"project")

    def test_restart_does_not_duplicate(self):
        Dispatcher(self.queue,lambda d:{}).run_once()
        self.assertEqual(Dispatcher(JobQueue(self.path),lambda d:{}).run_once()["dispatched"],0)
        with self.queue.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coding_jobs").fetchone()[0],1)

    def test_stale_or_paused_deferred(self):
        dispatcher = Dispatcher(self.queue,lambda d:None)
        self.assertEqual(dispatcher.run_once()["deferred"],1)
        self.assertIsNone(self.queue.claim())
        self.assertEqual(Dispatcher(self.queue,lambda d:{}).run_once()["dispatched"],1)

    def test_replay_after_enqueue_before_marker(self):
        dispatcher = Dispatcher(self.queue,lambda d:{"kind":"review"})
        dispatcher.run_once()
        with self.queue.transaction() as db:
            db.execute("DELETE FROM dispatched_decisions")
        self.assertEqual(dispatcher.run_once()["dispatched"],1)
        with self.queue.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coding_jobs").fetchone()[0],1)

    def test_invalid_resolver_result(self):
        with self.assertRaises(ValueError):
            Dispatcher(self.queue,lambda d:"not a job").run_once()
        self.assertIsNone(self.queue.claim())
