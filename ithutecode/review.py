"""Independent review gate. Trusted runtime must authenticate reviewer and
authoritative repository policy. This module does not authenticate identities.
"""
from dataclasses import dataclass, asdict
import hashlib
import json
import re

@dataclass(frozen=True)
class ReviewEvidence:
    project_id: str
    ordinal: int
    sha: str
    requirement_digest: str
    reviewer_id: str
    approved: bool
    findings: str
    evidence_refs: tuple[str, ...]

def requirement_digest(requirement):
    return hashlib.sha256(requirement.encode("utf-8")).hexdigest()

class ReviewGate:
    def __init__(self, store, github, resolve_policy, authenticate_review):
        self.store = store
        self.github = github
        self.resolve_policy = resolve_policy
        self.authenticate_review = authenticate_review

    def accept(self, evidence: ReviewEvidence):
        if not isinstance(evidence, ReviewEvidence):
            raise ValueError("Structured review evidence required")
        if not re.fullmatch(r"[0-9a-f]{40}", evidence.sha):
            raise ValueError("Invalid review commit")
        if evidence.approved is not True or not evidence.findings.strip():
            raise PermissionError("Independent approval required")
        if not evidence.evidence_refs or any(not isinstance(x,str) or not x.strip() for x in evidence.evidence_refs):
            raise ValueError("Evidence references required")
        if not self.authenticate_review(evidence):
            raise PermissionError("Review authentication failed")
        task = self.store.next_task(evidence.project_id)
        if task is None or task["ordinal"] != evidence.ordinal or task["candidate_sha"] != evidence.sha:
            raise PermissionError("Review does not match active candidate")
        if requirement_digest(task["requirement"]) != evidence.requirement_digest:
            raise PermissionError("Review does not match requirement")
        policy = self.resolve_policy(evidence.project_id)
        if evidence.reviewer_id not in policy["reviewers"] or evidence.reviewer_id in policy["authors"]:
            raise PermissionError("Independent authorized reviewer required")
        required = tuple(policy["required"])
        names = {c.name for c in required}
        if not names or len(names) != len(required):
            raise ValueError("Explicit unique CI requirements mandatory")
        checks = self.github.required_statuses(policy["repository_id"], evidence.sha, required)
        if set(checks) != names or any(v != "success" for v in checks.values()):
            raise PermissionError("Required CI checks not green")
        if self.resolve_policy(evidence.project_id) != policy or not self.authenticate_review(evidence):
            raise PermissionError("Review policy changed")
        record = json.dumps({"review":asdict(evidence),"checks":checks,
                             "repository_id":policy["repository_id"]},sort_keys=True)
        if len(record.encode()) > 200_000:
            raise ValueError("Review evidence too large")
        self.store.accept(evidence.project_id,evidence.ordinal,evidence.sha,record)
        return self.store.progress(evidence.project_id)
