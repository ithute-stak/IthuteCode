"""Project completion gate; certificates are evidence, not merge authorization.

Runtime must authenticate attestations, resolve trusted repository policy and
check the current remote branch head. No deployment or merge is performed.
"""
from dataclasses import dataclass, asdict
import hashlib
import json
import re

@dataclass(frozen=True)
class FinalEvidence:
    project_id: str
    sha: str
    requirements_digest: str
    reviewer_id: str
    passed_gates: tuple[str, ...]
    unresolved_defects: tuple[str, ...]
    evidence_refs: tuple[str, ...]

def digest_requirements(project, tasks):
    data = {"instruction":project["instruction"],"repository":project["repository"],
            "requirements":[[t["ordinal"],t["requirement"]] for t in tasks]}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

class CertificationGate:
    def __init__(self, store, github, resolve_policy, authenticate, remote_head, is_ancestor):
        self.store = store
        self.github = github
        self.resolve_policy = resolve_policy
        self.authenticate = authenticate
        self.remote_head = remote_head
        self.is_ancestor = is_ancestor
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS project_certificates (
                project_id TEXT NOT NULL REFERENCES projects(id), sha TEXT NOT NULL,
                record TEXT NOT NULL, PRIMARY KEY(project_id,sha)
            )""")

    def _snapshot(self, db, project_id):
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise KeyError(project_id)
        tasks = db.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY ordinal",
                           (project_id,)).fetchall()
        return dict(project), [dict(t) for t in tasks]

    def certify(self, evidence):
        if not isinstance(evidence, FinalEvidence) or not re.fullmatch(r"[0-9a-f]{40}",evidence.sha):
            raise ValueError("Exact final commit evidence required")
        if evidence.unresolved_defects or not evidence.evidence_refs or any(
            not isinstance(x,str) or not x.strip() for x in evidence.evidence_refs):
            raise PermissionError("Unresolved defects or missing evidence")
        with self.store.transaction() as db:
            project,tasks = self._snapshot(db,evidence.project_id)
        if project["paused"] or not tasks or any(
            not t["verified_sha"] or t["candidate_sha"] != t["verified_sha"] or not t["evidence"]
            for t in tasks):
            raise PermissionError("All tasks must be independently verified")
        if digest_requirements(project,tasks) != evidence.requirements_digest:
            raise PermissionError("Requirements mismatch")
        policy = self.resolve_policy(evidence.project_id)
        if evidence.reviewer_id not in policy["reviewers"] or evidence.reviewer_id in policy["authors"]:
            raise PermissionError("Independent final reviewer required")
        if not self.authenticate(evidence):
            raise PermissionError("Final evidence authentication failed")
        required_gates = set(policy["gates"])
        if not {"functional","regression","security"}.issubset(required_gates) or set(evidence.passed_gates) != required_gates:
            raise PermissionError("Mandatory certification gates not satisfied")
        repo,branch = policy["repository_id"],policy["branch"]
        if self.remote_head(repo,branch) != evidence.sha:
            raise PermissionError("Final commit is not current remote head")
        for task in tasks:
            if not self.is_ancestor(repo,task["verified_sha"],evidence.sha):
                raise PermissionError("Verified task absent from final history")
        required = tuple(policy["required"])
        names = {c.name for c in required}
        if not names or len(names) != len(required):
            raise ValueError("Explicit unique CI requirements mandatory")
        checks = self.github.required_statuses(repo,evidence.sha,required)
        if set(checks) != names or any(v != "success" for v in checks.values()):
            raise PermissionError("Final CI not green")
        if self.resolve_policy(evidence.project_id) != policy or not self.authenticate(evidence):
            raise PermissionError("Certification policy changed")
        if self.remote_head(repo,branch) != evidence.sha:
            raise PermissionError("Remote head changed")
        record = json.dumps({"evidence":asdict(evidence),"checks":checks,
            "repository_id":repo,"branch":branch,"tasks":len(tasks)},sort_keys=True)
        if len(record.encode()) > 200_000:
            raise ValueError("Certificate too large")
        with self.store.transaction() as db:
            if self._snapshot(db,evidence.project_id) != (project,tasks):
                raise PermissionError("Project changed during certification")
            old = db.execute("SELECT record FROM project_certificates WHERE project_id=? AND sha=?",
                             (evidence.project_id,evidence.sha)).fetchone()
            if old and old["record"] != record:
                raise ValueError("Conflicting certificate")
            db.execute("INSERT OR IGNORE INTO project_certificates VALUES (?,?,?)",
                       (evidence.project_id,evidence.sha,record))
        return {"status":"awaiting_approval","sha":evidence.sha,"verified_tasks":len(tasks)}
