import json
import unittest
from ithutecode.proposal import parse_proposal

class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.allowed = frozenset({"src/app.py"})
        self.edit = {"path":"src/app.py","expected_sha256":"a"*64,"content":"pass\n"}

    def test_valid(self):
        self.assertEqual(parse_proposal(json.dumps({"edits":[self.edit]}),self.allowed)[0].path,"src/app.py")

    def test_duplicate_key(self):
        with self.assertRaises(ValueError):
            parse_proposal('{"edits":[],"edits":[]}',self.allowed)

    def test_extra_fields(self):
        with self.assertRaises(ValueError):
            parse_proposal(json.dumps({"edits":[dict(self.edit, command="run")]}),self.allowed)

    def test_not_json(self):
        with self.assertRaises(ValueError):
            parse_proposal("run shell command",self.allowed)

    def test_unauthorized_path(self):
        with self.assertRaises(PermissionError):
            parse_proposal(json.dumps({"edits":[dict(self.edit,path="src/other.py")]}),self.allowed)
