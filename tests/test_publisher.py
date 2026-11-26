import unittest
from dataclasses import replace
from ithutecode.publisher import Publication, Publisher

class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.request = Publication("project",42,"ithutecode/demo","a"*40,"b"*40)
        self.calls = []
        self.remote = "a"*40
        self.publisher = Publisher(self,lambda request:True,lambda request:True)

    def publish(self,repository_id,branch,expected_sha,commit_sha):
        self.calls.append((repository_id,branch,expected_sha,commit_sha))
        if self.remote != expected_sha:
            raise RuntimeError("Remote branch changed")
        self.remote = commit_sha
        return self.remote

    def test_publish(self):
        self.assertEqual(self.publisher.publish(self.request),"b"*40)
        self.assertEqual(self.calls,[(42,"ithutecode/demo","a"*40,"b"*40)])

    def test_protected_branch(self):
        with self.assertRaises(PermissionError):
            self.publisher.publish(replace(self.request,branch="main"))
        self.assertEqual(self.calls,[])

    def test_stale_remote(self):
        self.remote = "c"*40
        with self.assertRaises(RuntimeError):
            self.publisher.publish(self.request)
        self.assertEqual(self.remote,"c"*40)

    def test_denied(self):
        with self.assertRaises(PermissionError):
            Publisher(self,lambda request:False,lambda request:True).publish(self.request)
        self.assertEqual(self.calls,[])

    def test_unverified_commit(self):
        with self.assertRaises(PermissionError):
            Publisher(self,lambda request:True,lambda request:False).publish(self.request)
        self.assertEqual(self.calls,[])

    def test_revoked(self):
        checks = iter([True,False])
        with self.assertRaises(PermissionError):
            Publisher(self,lambda request:next(checks),lambda request:True).publish(self.request)
        self.assertEqual(self.calls,[])

    def test_invalid_sha(self):
        with self.assertRaises(ValueError):
            self.publisher.publish(replace(self.request,commit_sha="HEAD"))
        self.assertEqual(self.calls,[])

    def test_no_change(self):
        with self.assertRaises(ValueError):
            self.publisher.publish(replace(self.request,commit_sha=self.request.baseline_sha))

    def test_unconfirmed_publication(self):
        class Uncertain:
            def publish(self,*args):
                return "c"*40
        with self.assertRaises(RuntimeError):
            Publisher(Uncertain(),lambda request:True,lambda request:True).publish(self.request)
