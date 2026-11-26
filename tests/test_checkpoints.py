import tempfile
import unittest
from pathlib import Path
from ithutecode.store import ProjectStore
from ithutecode.checkpoints import Checkpoints

class CheckpointTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/"state.db"
        self.store = ProjectStore(self.path)
        self.store.create_project("p","owner/repo","Build safely",["First","Second"])
        self.sha = "a"*40
        self.store.record_candidate("p",0,self.sha)
        self.checkpoints = Checkpoints(self.store)

    def verify(self,project,sha):
        return project == "p" and sha == self.sha

    def test_restart_recovers_original_instructions(self):
        self.checkpoints.save("p",self.sha,"Previous session notes",self.verify)
        reopened = Checkpoints(ProjectStore(self.path))
        data = reopened.recover("p",self.sha,self.verify)
        self.assertEqual(data["state"]["project"]["instruction"],"Build safely")
        self.assertEqual(data["state"]["tasks"][0]["candidate_sha"],self.sha)
        self.assertEqual(data["untrusted_notes"],"Previous session notes")

    def test_monotonic_sequences(self):
        self.assertEqual(self.checkpoints.save("p",self.sha,"One",self.verify),1)
        self.assertEqual(self.checkpoints.save("p",self.sha,"Two",self.verify),2)
        self.assertEqual(self.checkpoints.recover("p",self.sha,self.verify)["sequence"],2)

    def test_updated_task_state_discards_old_notes(self):
        self.checkpoints.save("p",self.sha,"Still working",self.verify)
        self.store.accept("p",0,self.sha,"Verified")
        data = self.checkpoints.recover("p",self.sha,self.verify)
        self.assertEqual(data["untrusted_notes"],"")
        self.assertEqual(data["state"]["tasks"][0]["verified_sha"],self.sha)
        self.assertIsNone(data["state"]["tasks"][1]["verified_sha"])

    def test_new_head_discards_old_notes(self):
        self.checkpoints.save("p",self.sha,"Old revision",self.verify)
        self.sha = "b"*40
        self.assertEqual(self.checkpoints.recover("p",self.sha,self.verify)["untrusted_notes"],"")

    def test_unverified_head_rejected(self):
        with self.assertRaises(PermissionError):
            self.checkpoints.save("p","b"*40,"Notes",self.verify)
        with self.assertRaises(PermissionError):
            self.checkpoints.recover("p","b"*40,self.verify)

    def test_project_isolation(self):
        self.checkpoints.save("p",self.sha,"Private notes",self.verify)
        self.store.create_project("q","owner/other","Other",["Other task"])
        data = self.checkpoints.recover("q",self.sha,lambda *args:True)
        self.assertEqual(data["untrusted_notes"],"")
        self.assertEqual(data["state"]["project"]["id"],"q")

    def test_corrupted_checkpoint_rejected(self):
        self.checkpoints.save("p",self.sha,"Notes",self.verify)
        with self.store.transaction() as db:
            db.execute("UPDATE development_checkpoints SET snapshot='tampered'")
        with self.assertRaises(RuntimeError):
            self.checkpoints.recover("p",self.sha,self.verify)

    def test_notes_bound(self):
        with self.assertRaises(ValueError):
            self.checkpoints.save("p",self.sha,"x"*24001,self.verify)

    def test_pause_state_preserved(self):
        self.checkpoints.save("p",self.sha,"Continue",self.verify)
        self.store.set_paused("p",True)
        data = self.checkpoints.recover("p",self.sha,self.verify)
        self.assertTrue(data["state"]["project"]["paused"])
        self.assertEqual(data["untrusted_notes"],"")
