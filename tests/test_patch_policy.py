import unittest
from dataclasses import replace
from ithutecode.patch_policy import Edit, validate_edits

class PatchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.edit = Edit("src/app.py", "a"*64, "print('ok')\n")
        self.allowed = frozenset({"src/app.py"})

    def test_authorized(self):
        self.assertEqual(validate_edits((self.edit,), self.allowed), (self.edit,))

    def test_traversal_and_absolute(self):
        for path in ("../app.py", "/app.py", "src/../app.py", "src\\app.py"):
            with self.subTest(path=path), self.assertRaises((ValueError, PermissionError)):
                validate_edits((replace(self.edit,path=path),), frozenset({path}))

    def test_protected_even_if_allowlisted(self):
        for path in (".github/workflow.py", "tests/check.py", "src/test_app.py", "src/conftest.py", ".git/config.py"):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                validate_edits((replace(self.edit,path=path),), frozenset({path}))

    def test_not_authorized(self):
        with self.assertRaises(PermissionError):
            validate_edits((self.edit,), frozenset({"src/other.py"}))

    def test_duplicate(self):
        with self.assertRaises(PermissionError):
            validate_edits((self.edit,self.edit), self.allowed)

    def test_missing_baseline(self):
        with self.assertRaises(ValueError):
            validate_edits((replace(self.edit,expected_sha256=""),), self.allowed)

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            validate_edits((replace(self.edit,content="x"*200001),), self.allowed)

    def test_binary_content(self):
        with self.assertRaises(ValueError):
            validate_edits((replace(self.edit,content="a\x00b"),), self.allowed)

    def test_empty_edits(self):
        with self.assertRaises(ValueError):
            validate_edits((), self.allowed)
