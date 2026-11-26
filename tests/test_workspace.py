import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from ithutecode.patch_policy import Edit
from ithutecode.workspace import apply_edits, source_context

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root/"src").mkdir()
        self.path = self.root/"src/app.py"
        self.path.write_bytes(b"old")
        self.allowed = frozenset({"src/app.py"})
        self.edit = Edit("src/app.py",hashlib.sha256(b"old").hexdigest(),"new")

    def test_context(self):
        file = json.loads(source_context(self.root,self.allowed))["authorized_files"][0]
        self.assertEqual(file["expected_sha256"],self.edit.expected_sha256)
        self.assertEqual(file["content"],"old")

    def test_apply(self):
        self.assertEqual(apply_edits(self.root,(self.edit,),self.allowed),("src/app.py",))
        self.assertEqual(self.path.read_bytes(),b"new")

    def test_stale(self):
        self.path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            apply_edits(self.root,(self.edit,),self.allowed)
        self.assertEqual(self.path.read_bytes(),b"changed")

    def test_preflight_all(self):
        (self.root/"src/other.py").write_bytes(b"other")
        bad = Edit("src/other.py","0"*64,"new")
        with self.assertRaises(ValueError):
            apply_edits(self.root,(self.edit,bad),self.allowed|{"src/other.py"})
        self.assertEqual(self.path.read_bytes(),b"old")

    def test_symlink(self):
        target = self.root/"target.py"
        target.write_bytes(b"old")
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(PermissionError):
            apply_edits(self.root,(self.edit,),self.allowed)
        self.assertEqual(target.read_bytes(),b"old")

    def test_hardlink(self):
        os.link(self.path,self.root/"alias.py")
        with self.assertRaises(PermissionError):
            apply_edits(self.root,(self.edit,),self.allowed)

    def test_no_change(self):
        with self.assertRaises(ValueError):
            apply_edits(self.root,(Edit(self.edit.path,self.edit.expected_sha256,"old"),),self.allowed)
