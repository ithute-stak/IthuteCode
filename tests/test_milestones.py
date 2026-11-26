import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from ithutecode.store import ProjectStore
from ithutecode.jobs import JobQueue
from ithutecode.checkpoints import Checkpoints
from ithutecode.journal import PublicationJournal
from ithutecode.publisher import Publication
from ithutecode.milestones import Milestones

class MilestoneTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/"state.db"
        self.store = ProjectStore(self.path)
        self.store.create_project("p","owner/repo","Build",["First","Second"])
        self.base,self.sha = "a"*40,"b"*40
        self.store.record_candidate("p",0,self.base)
        self.queue = JobQueue(self.path)
        self.queue.enqueue("job","p",{"decision":{"project_id":"p","sha":self.base}})
        self.claimed = self.queue.claim()
        self.journal = PublicationJournal(self.queue)
        self.checkpoints = Checkpoints(self.store)
        self.pub = Publication("p",42,"ithutecode/demo",self.base,self.sha)
        self.head = self.sha
        self.milestones = Milestones(self.checkpoints,self.journal,
            lambda repo,branch,sha: repo==42 and branch==self.pub.branch and sha==self.head)

    def confirm(self):
        self.journal.record_intent(self.claimed,self.pub)
        self.journal.record_published(self.claimed,self.pub)

    def test_published_candidate_and_checkpoint(self):
        self.confirm()
        self.assertEqual(self.milestones.record(self.claimed,self.pub,0),1)
        self.assertEqual(self.store.next_task("p")["candidate_sha"],self.sha)
        self.assertEqual(self.store.progress("p")["verified"],0)
        recovered = Checkpoints(ProjectStore(self.path)).recover("p",self.sha,lambda *args:True)
        self.assertEqual(recovered["sequence"],1)
        self.assertIn("review",recovered["untrusted_notes"])

    def test_idempotent_replay(self):
        self.confirm()
        self.assertEqual(self.milestones.record(self.claimed,self.pub,0),1)
        self.assertEqual(self.milestones.record(self.claimed,self.pub,0),1)

    def test_unconfirmed_publication(self):
        self.journal.record_intent(self.claimed,self.pub)
        with self.assertRaises(PermissionError):
            self.milestones.record(self.claimed,self.pub,0)
        self.assertEqual(self.store.next_task("p")["candidate_sha"],self.base)

    def test_remote_head_mismatch(self):
        self.confirm()
        self.head = "c"*40
        with self.assertRaises(PermissionError):
            self.milestones.record(self.claimed,self.pub,0)

    def test_wrong_lease(self):
        self.confirm()
        with self.assertRaises(PermissionError):
            self.milestones.record(dict(self.claimed,lease="wrong"),self.pub,0)

    def test_stale_task(self):
        self.confirm()
        self.store.record_candidate("p",0,"c"*40)
        with self.assertRaises(PermissionError):
            self.milestones.record(self.claimed,self.pub,0)

    def test_paused_project(self):
        self.confirm()
        self.store.set_paused("p",True)
        with self.assertRaises(ValueError):
            self.milestones.record(self.claimed,self.pub,0)

    def test_atomic_rollback_on_checkpoint_failure(self):
        self.confirm()
        with self.store.transaction() as db:
            db.execute("UPDATE projects SET instruction=? WHERE id='p'",("x"*200001,))
        with self.assertRaises(ValueError):
            self.milestones.record(self.claimed,self.pub,0)
        self.assertEqual(self.store.next_task("p")["candidate_sha"],self.base)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM development_checkpoints").fetchone()[0],0)
