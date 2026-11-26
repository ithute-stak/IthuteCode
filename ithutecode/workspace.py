"""Controlled edits in an exclusive disposable checkout, not a security sandbox.

Never use on a shared or actively running checkout. A failed write invalidates
the entire workspace; the caller must discard it. No repository code is run.
"""
import hashlib
import json
import os
import stat
from pathlib import Path
from .patch_policy import Edit, validate_edits

def _read_source(root: Path, path: str) -> tuple[Path, bytes]:
    current = root
    for part in path.split("/"):
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise PermissionError("Symlink rejected")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PermissionError("Not an exclusive regular file")
    if info.st_size > 200_000:
        raise ValueError("Baseline too large")
    with current.open("rb") as handle:
        content = handle.read(200_001)
    if len(content) > 200_000:
        raise ValueError("Baseline too large")
    return current, content

def _root(path):
    root = Path(path).absolute()
    if root.resolve(strict=True) != root or not root.is_dir():
        raise PermissionError("Workspace must be a real directory")
    return root

def source_context(root, allowed_paths):
    root = _root(root)
    if not 1 <= len(allowed_paths) <= 20:
        raise ValueError("Invalid authorized path count")
    validate_edits(tuple(Edit(p, "0"*64, "") for p in sorted(allowed_paths)), allowed_paths)
    files = []
    total = 0
    for path in sorted(allowed_paths):
        _, raw = _read_source(root, path)
        total += len(raw)
        if total > 80_000:
            raise ValueError("Source context too large")
        files.append({"path": path, "expected_sha256": hashlib.sha256(raw).hexdigest(),
                      "content": raw.decode("utf-8")})
    return json.dumps({"authorized_files": files})

def apply_edits(root, edits, allowed_paths):
    root = _root(root)
    validate_edits(edits, allowed_paths)
    planned = []
    for edit in edits:
        path, original = _read_source(root, edit.path)
        if hashlib.sha256(original).hexdigest() != edit.expected_sha256:
            raise ValueError("Baseline checksum mismatch")
        updated = edit.content.encode("utf-8")
        if updated != original:
            planned.append((path, original, updated))
    if not planned:
        raise ValueError("Proposal makes no changes")
    # Preflight all files before any write. Exclusive workspace ownership is required.
    for path, original, updated in planned:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, "r+b") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PermissionError("Unsafe file")
            if handle.read(200_001) != original:
                raise ValueError("Baseline changed")
            handle.seek(0)
            handle.write(updated)
            handle.truncate()
    return tuple(str(path.relative_to(root)) for path, _, _ in planned)
