import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from ithutecode.jobs import JobQueue

class JobQueueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "jobs.db"
        self.now = 100
        self.queue = JobQueue(self.path, lambda: self.now)

    def test_duplicate_and_collision(self):
        self.assertTrue(self.queue.enqueue("one", "project", {"task":1}))
        self.assertFalse(self.queue.enqueue("one", "project", {"task":1}))
        with self.assertRaises(ValueError):
            self.queue.enqueue("one", "project", {"task":2})

    def test_restart(self):
        self.queue.enqueue("one", "project", {"task":1})
        reopened = JobQueue(self.path, lambda: self.now)
        self.assertEqual(reopened.claim()["payload"], {"task":1})

    def test_concurrent_claim(self):
        self.queue.enqueue("one", "project", {})
        self.queue.enqueue("two", "project", {})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.queue.claim(), range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_separate_projects(self):
        self.queue.enqueue("one", "a", {})
        self.queue.enqueue("two", "b", {})
        self.assertEqual(self.queue.claim()["project_id"], "a")
        self.assertEqual(self.queue.claim()["project_id"], "b")

    def test_finish_and_next(self):
        self.queue.enqueue("one", "project", {})
        self.queue.enqueue("two", "project", {})
        job = self.queue.claim()
        self.queue.finish(job["id"], job["lease"], {"commit":"abc"})
        self.assertEqual(self.queue.status("one")["status"], "completed")
        self.assertEqual(self.queue.claim()["id"], "two")

    def test_invalid_lease(self):
        self.queue.enqueue("one", "project", {})
        self.queue.claim()
        with self.assertRaises(PermissionError):
            self.queue.finish("one", "incorrect", {})
        self.assertEqual(self.queue.status("one")["status"], "running")

    def test_expired_requires_reconciliation(self):
        self.queue.enqueue("one", "project", {})
        self.queue.enqueue("two", "project", {})
        job = self.queue.claim(10)
        self.now += 10
        with self.assertRaises(PermissionError):
            self.queue.finish("one", job["lease"], {})
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.status("one")["status"], "uncertain")
        with self.assertRaises(ValueError):
            self.queue.reconcile("one", job["lease"], "failed", "")
        self.queue.reconcile("one", job["lease"], "failed", "Verified worker stopped and no push")
        self.assertEqual(self.queue.claim()["id"], "two")

    def test_payload_bounds(self):
        with self.assertRaises(ValueError):
            self.queue.enqueue("one", "project", {"text":"x"*200001})
        with self.assertRaises(ValueError):
            self.queue.claim(0)
