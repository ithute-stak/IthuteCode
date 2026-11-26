import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from ithutecode.jobs import JobQueue
from ithutecode.publisher import Publication
from ithutecode.journal import PublicationJournal
from ithutecode.budget import BudgetLedger

class AccountingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/"state.db"
        self.now = 100
        self.queue = JobQueue(self.path, lambda:self.now)
        self.queue.enqueue("one","project",{})
        self.job = self.queue.claim(10)
        self.journal = PublicationJournal(self.queue)
        self.budget = BudgetLedger(self.queue)
        self.publication = Publication("project",42,"ithutecode/demo","a"*40,"b"*40)

    def test_publication_survives_restart(self):
        self.journal.record_intent(self.job,self.publication)
        reopened = PublicationJournal(JobQueue(self.path,lambda:self.now))
        self.assertEqual(reopened.inspect("one")["status"],"intent")
        reopened.record_published(self.job,self.publication)
        self.assertEqual(self.journal.inspect("one")["status"],"published")

    def test_duplicate_intent_rejected(self):
        self.journal.record_intent(self.job,self.publication)
        with self.assertRaises(RuntimeError):
            self.journal.record_intent(self.job,self.publication)

    def test_confirmation_requires_matching_intent(self):
        with self.assertRaises(RuntimeError):
            self.journal.record_published(self.job,self.publication)
        self.journal.record_intent(self.job,self.publication)
        with self.assertRaises(RuntimeError):
            self.journal.record_published(self.job,replace(self.publication,commit_sha="c"*40))

    def test_expired_lease(self):
        self.budget.configure("project",100)
        self.now += 11
        with self.assertRaises(PermissionError):
            self.journal.record_intent(self.job,self.publication)
        with self.assertRaises(PermissionError):
            self.budget.reserve(self.job,10)

    def test_budget_reservation_and_settlement(self):
        self.budget.configure("project",100)
        self.budget.reserve(self.job,60)
        self.assertEqual(self.budget.balance("project")["remaining"],40)
        self.budget.settle("one",30)
        self.assertEqual(self.budget.balance("project")["remaining"],70)
        self.budget.settle("one",30)
        with self.assertRaises(ValueError):
            self.budget.settle("one",0)

    def test_budget_missing_and_exhausted(self):
        with self.assertRaises(PermissionError):
            self.budget.reserve(self.job,10)
        self.budget.configure("project",5)
        with self.assertRaises(PermissionError):
            self.budget.reserve(self.job,10)

    def test_duplicate_reservation_and_recovery(self):
        self.budget.configure("project",100)
        self.budget.reserve(self.job,80)
        reopened = BudgetLedger(JobQueue(self.path,lambda:self.now))
        self.assertEqual(reopened.balance("project")["remaining"],20)
        with self.assertRaises(RuntimeError):
            reopened.reserve(self.job,10)

    def test_overrun_blocks_next_job(self):
        self.budget.configure("project",100)
        self.budget.reserve(self.job,80)
        self.budget.settle("one",110)
        self.queue.finish("one",self.job["lease"],{})
        self.queue.enqueue("two","project",{})
        second = self.queue.claim()
        with self.assertRaises(PermissionError):
            self.budget.reserve(second,1)
        self.assertEqual(self.budget.balance("project")["remaining"],-10)

    def test_wrong_project_rejected(self):
        self.budget.configure("other",100)
        forged = dict(self.job,project_id="other")
        with self.assertRaises(PermissionError):
            self.budget.reserve(forged,10)
        with self.assertRaises(PermissionError):
            self.journal.record_intent(forged,replace(self.publication,project_id="other"))
