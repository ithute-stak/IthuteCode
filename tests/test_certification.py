import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from ithutecode.store import ProjectStore
from ithutecode.ci import RequiredCheck
from ithutecode.certification import CertificationGate, FinalEvidence, digest_requirements

class CertificationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ProjectStore(Path(tmp.name)/"state.db")
        self.store.create_project("p","owner/repo","Build",["One","Two"])
        self.first, self.final = "a"*40, "b"*40
        self.store.record_candidate("p",0,self.first)
        self.store.accept("p",0,self.first,"review-one")
        self.store.record_candidate("p",1,self.final)
        self.store.accept("p",1,self.final,"review-two")
        self.policy = {"repository_id":42,"branch":"ithutecode/demo",
                       "reviewers":frozenset({"reviewer","author"}),"authors":frozenset({"author"}),
                       "gates":("functional","regression","security"),
                       "required":(RequiredCheck("tests",12),)}
        self.head = self.final
        self.checks = {"tests":"success"}
        self.auth = True
        self.ancestry = True
        self.gate = CertificationGate(self.store,self,lambda p:self.policy,
            lambda e:self.auth,lambda repo,branch:self.head,lambda *args:self.ancestry)
        with self.store.transaction() as db:
            project,tasks = self.gate._snapshot(db,"p")
        self.evidence = FinalEvidence("p",self.final,digest_requirements(project,tasks),
            "reviewer",self.policy["gates"],(),("final-report",))

    def required_statuses(self,repo,sha,required):
        self.assertEqual((repo,sha),(42,self.final))
        return self.checks

    def test_certification_and_replay(self):
        expected = {"status":"awaiting_approval","sha":self.final,"verified_tasks":2}
        self.assertEqual(self.gate.certify(self.evidence),expected)
        self.assertEqual(self.gate.certify(self.evidence),expected)
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM project_certificates").fetchone()[0],1)

    def test_unfinished_task(self):
        with self.store.transaction() as db:
            db.execute("UPDATE tasks SET verified_sha=NULL WHERE ordinal=1")
        with self.assertRaises(PermissionError):
            self.gate.certify(self.evidence)

    def test_missing_gate_or_defect(self):
        for e in (replace(self.evidence,passed_gates=("functional","regression")),
                  replace(self.evidence,unresolved_defects=("bug",)),
                  replace(self.evidence,evidence_refs=())):
            with self.assertRaises(PermissionError):
                self.gate.certify(e)

    def test_stale_head(self):
        self.head = "c"*40
        with self.assertRaises(PermissionError):
            self.gate.certify(self.evidence)

    def test_missing_ancestry(self):
        self.ancestry = False
        with self.assertRaises(PermissionError):
            self.gate.certify(self.evidence)

    def test_ci_not_green(self):
        for checks in ({},{"tests":"failure"},{"tests":"skipped"}):
            self.checks = checks
            with self.assertRaises(PermissionError):
                self.gate.certify(self.evidence)

    def test_independence_and_authentication(self):
        with self.assertRaises(PermissionError):
            self.gate.certify(replace(self.evidence,reviewer_id="author"))
        self.auth = False
        with self.assertRaises(PermissionError):
            self.gate.certify(self.evidence)

    def test_requirement_mismatch(self):
        with self.assertRaises(PermissionError):
            self.gate.certify(replace(self.evidence,requirements_digest="wrong"))

    def test_pause(self):
        self.store.set_paused("p",True)
        with self.assertRaises(PermissionError):
            self.gate.certify(self.evidence)
