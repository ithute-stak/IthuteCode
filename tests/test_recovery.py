import tempfile
import unittest
from pathlib import Path
from ithutecode.store import ProjectStore
from ithutecode.jobs import JobQueue
from ithutecode.checkpoints import Checkpoints
from ithutecode.journal import PublicationJournal
from ithutecode.publisher import Publication
from ithutecode.milestones import Milestones
from ithutecode.recovery import PublicationRecovery

class RecoveryTests(unittest.TestCase):
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
        self.stopped = True
        self.allowed = True
        self.milestones = Milestones(self.checkpoints,self.journal,
            lambda repo,branch,sha: repo==42 and branch==self.pub.branch and sha==self.head)
        self.recovery = PublicationRecovery(self.milestones,
            lambda *args:self.allowed,lambda *args:self.stopped,
            lambda *args:self.head,lambda *args:0)

    def interrupt(self, confirmed=False):
        self.journal.record_intent(self.claimed,self.pub)
        if confirmed:
            self.journal.record_published(self.claimed,self.pub)
        self.queue.mark_uncertain("job",self.claimed["lease"])

    def test_recover_after_unrecorded_push(self):
        self.interrupt()
        self.assertEqual(self.recovery.recover("job"),"recovered")
        self.assertEqual(self.queue.status("job")["status"],"completed")
        self.assertEqual(self.journal.inspect("job")["status"],"published")
        self.assertEqual(self.store.next_task("p")["candidate_sha"],self.sha)
        self.assertEqual(self.store.progress("p")["verified"],0)
        self.assertEqual(self.checkpoints.recover("p",self.sha,lambda *args:True)["sequence"],1)

    def test_recover_confirmed_push(self):
        self.interrupt(True)
        self.assertEqual(self.recovery.recover("job"),"recovered")

    def test_recover_after_checkpoint_before_completion(self):
        self.journal.record_intent(self.claimed,self.pub)
        self.journal.record_published(self.claimed,self.pub)
        self.milestones.record(self.claimed,self.pub,0)
        self.queue.mark_uncertain("job",self.claimed["lease"])
        self.assertEqual(self.recovery.recover("job"),"recovered")
        self.assertEqual(self.recovery.recover("job"),"not_eligible")
        self.assertEqual(self.checkpoints.recover("p",self.sha,lambda *args:True)["sequence"],1)

    def test_worker_must_be_stopped(self):
        self.interrupt()
        self.stopped = False
        self.assertEqual(self.recovery.recover("job"),"blocked")
        self.assertEqual(self.queue.status("job")["status"],"uncertain")

    def test_authorization_required(self):
        self.interrupt()
        self.allowed = False
        self.assertEqual(self.recovery.recover("job"),"blocked")

    def test_remote_baseline_or_divergence_stays_blocked(self):
        self.interrupt()
        for head in (self.base,"c"*40,None):
            self.head=head
            self.assertEqual(self.recovery.recover("job"),"blocked")
        self.assertEqual(self.journal.inspect("job")["status"],"intent")

    def test_running_job_ineligible(self):
        self.journal.record_intent(self.claimed,self.pub)
        self.assertEqual(self.recovery.recover("job"),"not_eligible")

    def test_paused_project_rolls_back_recovery(self):
        self.interrupt()
        self.store.set_paused("p",True)
        with self.assertRaises(ValueError):
            self.recovery.recover("job")
        self.assertEqual(self.journal.inspect("job")["status"],"intent")
        self.assertEqual(self.queue.status("job")["status"],"uncertain")
