import hashlib
import hmac
import io
import json
import tempfile
import unittest
from pathlib import Path
from ithutecode.github_client import GitHubClient
from ithutecode.github_events import Inbox
from ithutecode.webhook import application
from ithutecode.ci import RequiredCheck

SHA = "a" * 40

class ClientTests(unittest.TestCase):
    def test_required_status(self):
        run = {"id":1,"head_sha":SHA,"name":"tests","app":{"id":12},"status":"completed","conclusion":"success"}
        def transport(url, token):
            self.assertTrue(url.startswith("https://api.github.com/repositories/42/"))
            self.assertEqual(token,"fake")
            return {"total_count":1,"check_runs":[run]}
        client = GitHubClient(lambda repo: "fake", transport)
        self.assertEqual(client.required_statuses(42,SHA,(RequiredCheck("tests",12),)),{"tests":"success"})

    def test_pagination(self):
        def transport(url, token):
            ids = range(100) if url.endswith("page=1") else [100]
            return {"total_count":101,"check_runs":[{"id":i} for i in ids]}
        self.assertEqual(len(GitHubClient(lambda repo:"fake",transport).check_runs(42,SHA)),101)

    def test_incomplete_response(self):
        client = GitHubClient(lambda repo:"fake",lambda u,t:{"total_count":2,"check_runs":[{"id":1}]})
        with self.assertRaises(RuntimeError):
            client.check_runs(42,SHA)

    def test_page_limit(self):
        client = GitHubClient(lambda repo:"fake",lambda u,t:{"total_count":101,"check_runs":[{"id":i} for i in range(100)]},max_pages=1)
        with self.assertRaises(RuntimeError):
            client.check_runs(42,SHA)

    def test_invalid_repository(self):
        with self.assertRaises(ValueError):
            GitHubClient(lambda repo:"fake").check_runs("42/evil",SHA)

class WebhookTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.inbox = Inbox(Path(tmp.name)/"db")
        self.app = application(self.inbox,b"secret",frozenset({42}))
        self.body = json.dumps({"action":"completed","repository":{"id":42},"workflow_run":{"head_sha":SHA}}).encode()
        self.sig = "sha256=" + hmac.new(b"secret",self.body,hashlib.sha256).hexdigest()

    def send(self, **changes):
        env = {"PATH_INFO":"/webhooks/github","REQUEST_METHOD":"POST","CONTENT_LENGTH":str(len(self.body)),
               "wsgi.input":io.BytesIO(self.body),"HTTP_X_HUB_SIGNATURE_256":self.sig,
               "HTTP_X_GITHUB_EVENT":"workflow_run","HTTP_X_GITHUB_DELIVERY":"one"}
        env.update(changes)
        status = []
        list(self.app(env,lambda s,h:status.append(s)))
        return status[0]

    def test_signed_and_duplicate(self):
        self.assertEqual(self.send(),"202 Accepted")
        self.assertEqual(self.send(),"202 Accepted")
        self.assertEqual(len(self.inbox.pending()),1)

    def test_invalid_signature(self):
        self.assertEqual(self.send(HTTP_X_HUB_SIGNATURE_256="bad"),"403 Forbidden")
        self.assertEqual(self.inbox.pending(),[])

    def test_invalid_size(self):
        self.assertEqual(self.send(CONTENT_LENGTH="2000001"),"400 Bad Request")

    def test_wrong_method(self):
        self.assertEqual(self.send(REQUEST_METHOD="GET"),"405 Method Not Allowed")
