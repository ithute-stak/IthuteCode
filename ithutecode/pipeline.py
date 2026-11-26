"""One local coding cycle in a trusted disposable checkout.

No remote publishing, execution of repository code, or live budget accounting.
The caller must discard the checkout on failure and enforce exclusive ownership.
"""
from dataclasses import dataclass, replace
import re
from .agent import CodingRequest
from .git_workspace import GitWorkspace
from .proposal import parse_proposal
from .workspace import source_context

@dataclass(frozen=True)
class CodingJob:
    request: CodingRequest
    branch: str
    allowed_paths: frozenset[str]

@dataclass(frozen=True)
class CodingResult:
    project_id: str
    baseline_sha: str
    commit_sha: str
    branch: str

class CodingPipeline:
    def __init__(self, agent, authorize):
        self.agent = agent
        self.authorize = authorize

    def run(self, root, job: CodingJob) -> CodingResult:
        if not self.authorize(job):
            raise PermissionError("Coding job not authorized")
        sha = job.request.candidate_sha
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid baseline")
        if not isinstance(job.branch, str) or not re.fullmatch(r"ithutecode/[a-z0-9][a-z0-9-]{0,79}", job.branch):
            raise PermissionError("Dedicated development branch required")
        workspace = GitWorkspace(root)
        if workspace._git("rev-parse", "HEAD").decode().strip() != sha:
            raise ValueError("Stale job baseline")
        if workspace._git("symbolic-ref", "--short", "HEAD").decode().strip() != job.branch:
            raise PermissionError("Unexpected branch")
        if workspace._git("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            raise ValueError("Workspace is not clean")
        context = source_context(workspace.root, job.allowed_paths)
        proposal = self.agent.propose(replace(job.request, context=context))
        edits = parse_proposal(proposal, job.allowed_paths)
        if not self.authorize(job):
            raise PermissionError("Coding authorization withdrawn")
        commit = workspace.commit_edits(sha, job.branch, edits, job.allowed_paths)
        return CodingResult(job.request.project_id, sha, commit, job.branch)
