import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from ithutecode.github_events import authenticate_notice, Inbox, Notice
from ithutecode.ci import RequiredCheck, reconcile

SHA = "a" * 40

class GitHubEventsTests(unittest.TestCase):
    def setUp(self):
        self.body = json.dumps({"action":"completed", "repository":{"id":42},
                                "workflow_run":{"head_sha":SHA,"conclusion":"success"}}).encode()
        self.secret = b"test-secret"
        self.signature = "sha256=" + hmac.new(self.secret,self.body,hashlib.sha256).hexdigest()

    def test_valid_notice(self):
        self.assertEqual(authenticate_notice(self.body,self.signature,"workflow_run",self.secret,frozenset({42})), Notice(42,SHA))

    def test_tampered_body(self):
        with self.assertRaises(PermissionError):
            authenticate_notice(self.body+b" ",self.signature,"workflow_run",self.secret,frozenset({42}))

    def test_wrong_repository(self):
        with self.assertRaises(PermissionError):
            authenticate_notice(self.body,self.signature,"workflow_run",self.secret,frozenset({43}))

    def test_replay_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"inbox.db"
            inbox = Inbox(path)
            self.assertTrue(inbox.enqueue("delivery-1",Notice(42,SHA)))
            self.assertFalse(inbox.enqueue("delivery-1",Notice(42,SHA)))
            self.assertEqual(Inbox(path).pending(),[("delivery-1",42,SHA)])
            inbox.acknowledge("delivery-1")
            self.assertEqual(Inbox(path).pending(),[])

class CITests(unittest.TestCase):
    def setUp(self):
        self.required = (RequiredCheck("tests",12),)
        self.run = {"head_sha":SHA,"name":"tests","app":{"id":12},"status":"completed","conclusion":"success"}

    def test_success(self):
        self.assertEqual(reconcile(SHA,self.required,[self.run]),{"tests":"success"})

    def test_stale_or_untrusted(self):
        for run in (dict(self.run,head_sha="b"*40),dict(self.run,app={"id":99})):
            self.assertEqual(reconcile(SHA,self.required,[run]),{"tests":"missing"})

    def test_duplicates_are_ambiguous(self):
        self.assertEqual(reconcile(SHA,self.required,[self.run,self.run]),{"tests":"ambiguous"})

    def test_running_is_not_green(self):
        self.assertEqual(reconcile(SHA,self.required,[dict(self.run,status="in_progress")]),{"tests":"pending"})

    def test_empty_required_rejected(self):
        with self.assertRaises(ValueError):
            reconcile(SHA,(),[self.run])
