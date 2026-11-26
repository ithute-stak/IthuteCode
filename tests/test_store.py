import tempfile
import unittest
from pathlib import Path
from ithutecode.store import ProjectStore

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "projects.db"
        self.store = ProjectStore(self.path)
        self.store.create_project("a", "owner/repo", "Build", ["first", "second"])
        self.sha = "a" * 40

    def test_restart(self):
        self.store.record_candidate("a", 0, self.sha)
        self.store.accept("a", 0, self.sha, "review evidence")
        reopened = ProjectStore(self.path)
        self.assertEqual(reopened.next_task("a")["ordinal"], 1)
        self.assertEqual(reopened.progress("a"), {"total": 2, "verified": 1})

    def test_stale_and_missing_evidence(self):
        self.store.record_candidate("a", 0, self.sha)
        self.store.record_candidate("a", 0, "b" * 40)
        with self.assertRaises(ValueError):
            self.store.accept("a", 0, self.sha, "old")
        with self.assertRaises(ValueError):
            self.store.accept("a", 0, "b" * 40, "")
        self.assertEqual(self.store.progress("a")["verified"], 0)

    def test_order_and_pause(self):
        with self.assertRaises(ValueError):
            self.store.record_candidate("a", 1, self.sha)
        self.store.set_paused("a", True)
        self.assertIsNone(ProjectStore(self.path).next_task("a"))
        with self.assertRaises(ValueError):
            self.store.record_candidate("a", 0, self.sha)
        self.store.set_paused("a", False)
        self.assertEqual(self.store.next_task("a")["ordinal"], 0)

    def test_project_separation(self):
        self.store.create_project("b", "owner/other", "Other", ["only"])
        self.store.record_candidate("a", 0, self.sha)
        self.store.accept("a", 0, self.sha, "evidence")
        self.assertEqual(self.store.progress("b"), {"total": 1, "verified": 0})

    def test_duplicate_project_does_not_replace_tasks(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_project("a", "owner/other", "Other", ["only"])
        self.assertEqual(self.store.progress("a")["total"], 2)

    def test_finished(self):
        for ordinal in range(2):
            self.store.record_candidate("a", ordinal, self.sha)
            self.store.accept("a", ordinal, self.sha, "evidence")
        self.assertIsNone(self.store.next_task("a"))
        self.assertEqual(self.store.progress("a")["verified"], 2)
