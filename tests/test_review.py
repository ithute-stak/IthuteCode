import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from ithutecode.store import ProjectStore
from ithutecode.ci import RequiredCheck
from ithutecode.review import ReviewEvidence, ReviewGate, requirement_digest

class ReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ProjectStore(Path(tmp.name)/"state.db")
        self.store.create_project("p","owner/repo","Build",["Add feature","Next feature"])
        self.sha = "a"*40
        self.store.record_candidate("p",0,self.sha)
        self.policy = {"repository_id":42,"reviewers":frozenset({"reviewer","author"}),
                       "authors":frozenset({"author"}),"required":(RequiredCheck("tests",12),)}
        self.checks = {"tests":"success"}
        self.auth = True
        self.gate = ReviewGate(self.store,self,lambda p:self.policy,lambda e:self.auth)
        self.evidence = ReviewEvidence("p",0,self.sha,requirement_digest("Add feature"),
                                       "reviewer",True,"Verified requirement",("test-report",))

    def required_statuses(self,repo,sha,required):
        self.assertEqual(repo,42)
        self.assertEqual(sha,self.sha)
        return self.checks

    def test_accepted_and_next(self):
        self.assertEqual(self.gate.accept(self.evidence),{"total":2,"verified":1})
        self.assertEqual(self.store.next_task("p")["ordinal"],1)

    def test_author_cannot_review(self):
        with self.assertRaises(PermissionError):
            self.gate.accept(replace(self.evidence,reviewer_id="author"))

    def test_unauthenticated_review(self):
        self.auth = False
        with self.assertRaises(PermissionError):
            self.gate.accept(self.evidence)

    def test_stale_commit_or_requirement(self):
        for evidence in (replace(self.evidence,sha="b"*40),
                         replace(self.evidence,requirement_digest=requirement_digest("Different"))):
            with self.assertRaises(PermissionError):
                self.gate.accept(evidence)

    def test_ci_must_be_green(self):
        for checks in ({},{"tests":"failure"},{"tests":"pending"},{"tests":"skipped"}):
            self.checks = checks
            with self.assertRaises(PermissionError):
                self.gate.accept(self.evidence)
        self.assertEqual(self.store.progress("p")["verified"],0)

    def test_missing_evidence(self):
        with self.assertRaises(ValueError):
            self.gate.accept(replace(self.evidence,evidence_refs=()))

    def test_rejected_review(self):
        with self.assertRaises(PermissionError):
            self.gate.accept(replace(self.evidence,approved=False))

    def test_paused_project(self):
        self.store.set_paused("p",True)
        with self.assertRaises(PermissionError):
            self.gate.accept(self.evidence)
