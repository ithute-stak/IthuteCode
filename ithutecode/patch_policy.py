"""Validate structured edits before any filesystem or Git operation.

This is not a sandbox. The execution layer must independently verify paths,
baseline file contents, repository identity, and authorization at execution.
"""
from dataclasses import dataclass
import re

_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
_PROTECTED = frozenset({".git", ".github", ".gitlab", ".gitmodules", ".gitattributes",
                        ".gitignore", ".env", "tests", "test", "conftest.py",
                        "pytest.ini", "tox.ini", "pyproject.toml", "makefile",
                        "dockerfile", "codeowners", "package.json", "package-lock.json",
                        "requirements.txt", "setup.py", "setup.cfg", "node_modules"})

@dataclass(frozen=True)
class Edit:
    path: str
    expected_sha256: str
    content: str

def validate_edits(edits: tuple[Edit, ...], allowed_paths: frozenset[str]) -> tuple[Edit, ...]:
    """MVP permits replacements of explicitly authorized existing source files only."""
    if not 1 <= len(edits) <= 20 or not allowed_paths:
        raise ValueError("Invalid edit count or empty authorization")
    seen = set()
    total = 0
    for edit in edits:
        if not isinstance(edit, Edit) or not isinstance(edit.path, str):
            raise ValueError("Invalid edit")
        path = edit.path
        if len(path) > 240 or not _PATH.fullmatch(path):
            raise ValueError("Invalid path")
        parts = path.split("/")
        if any(part in {".", ".."} or part.startswith(".") or
               part.casefold() in _PROTECTED or part.casefold().startswith(("test_", "dockerfile", "compose.", "requirements"))
               for part in parts):
            raise PermissionError("Protected path")
        if not path.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
            raise PermissionError("Unsupported source file type")
        if path not in allowed_paths or path.casefold() in seen:
            raise PermissionError("Unauthorized or duplicate path")
        seen.add(path.casefold())
        if not isinstance(edit.expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", edit.expected_sha256):
            raise ValueError("Missing baseline content hash")
        if not isinstance(edit.content, str) or "\x00" in edit.content:
            raise ValueError("Invalid file content")
        total += len(edit.content.encode("utf-8"))
        if total > 200_000:
            raise ValueError("Edit size limit exceeded")
    return edits
