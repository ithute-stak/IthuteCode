"""Remote publishing contract; transport must enforce atomic ref comparison.
No live credentials or unrestricted Git commands are accepted here.
"""
from dataclasses import dataclass
from typing import Protocol
import re

@dataclass(frozen=True)
class Publication:
    project_id: str
    repository_id: int
    branch: str
    baseline_sha: str
    commit_sha: str

class Transport(Protocol):
    def publish(self, repository_id: int, branch: str, expected_sha: str,
                commit_sha: str) -> str: ...

class Publisher:
    def __init__(self, transport: Transport, authorize, verify_commit):
        self.transport = transport
        self.authorize = authorize
        self.verify_commit = verify_commit

    def publish(self, request: Publication) -> str:
        if type(request.repository_id) is not int or request.repository_id <= 0:
            raise ValueError("Invalid repository ID")
        if not isinstance(request.project_id, str) or not request.project_id.strip():
            raise ValueError("Invalid project")
        if not isinstance(request.branch, str) or not re.fullmatch(r"ithutecode/[a-z0-9][a-z0-9-]{0,79}", request.branch):
            raise PermissionError("Dedicated development branch required")
        for sha in (request.baseline_sha, request.commit_sha):
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("Invalid commit SHA")
        if request.baseline_sha == request.commit_sha:
            raise ValueError("No new commit")
        if not self.authorize(request):
            raise PermissionError("Publication not authorized")
        if not self.verify_commit(request):
            raise PermissionError("Commit provenance or contents not verified")
        if not self.authorize(request):
            raise PermissionError("Publication authorization withdrawn")
        observed = self.transport.publish(request.repository_id, request.branch,
                                          request.baseline_sha, request.commit_sha)
        if observed != request.commit_sha:
            raise RuntimeError("Publication not confirmed; reconcile before retry")
        return observed
