"""Single-pass reconciliation worker. No external coding side effects."""
import sqlite3
import json
from dataclasses import dataclass, replace
from .engine import Snapshot, Decision, decide
from .ci import RequiredCheck

@dataclass(frozen=True)
class Target:
    project_id: str
    repository_id: int
    ordinal: int
    snapshot: Snapshot
    required: tuple[RequiredCheck, ...]

class DecisionOutbox:
    def __init__(self, path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Durable database required")
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS decision_outbox (
                project_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                sha TEXT NOT NULL, decision TEXT NOT NULL,
                attempt INTEGER NOT NULL, evidence TEXT NOT NULL,
                PRIMARY KEY(project_id, ordinal, sha, decision, attempt)
            )""")

    def record(self, target, decision, checks):
        if decision not in {Decision.REPAIR, Decision.REVIEW, Decision.NEXT_TASK, Decision.APPROVAL}:
            return False
        s = target.snapshot
        attempt = s.repair_attempts if decision == Decision.REPAIR else 0
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT OR IGNORE INTO decision_outbox VALUES (?,?,?,?,?,?)",
                (target.project_id, target.ordinal, s.candidate_sha,
                 decision.value, attempt, json.dumps(checks, sort_keys=True)))
            return cur.rowcount == 1

    def entries(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT * FROM decision_outbox ORDER BY rowid").fetchall()

class Worker:
    def __init__(self, inbox, outbox, github, resolve_targets):
        self.inbox = inbox
        self.outbox = outbox
        self.github = github
        self.resolve_targets = resolve_targets

    def run_once(self):
        """Resolve targets from trusted state; leave failures pending for retry."""
        processed, failed = 0, 0
        for delivery, repository_id, sha in self.inbox.pending():
            try:
                for target in self.resolve_targets(repository_id, sha):
                    if target.repository_id != repository_id or target.snapshot.candidate_sha != sha:
                        continue
                    if tuple(c.name for c in target.required) != target.snapshot.required_checks:
                        raise ValueError("Required check policy mismatch")
                    if target.snapshot.paused or not target.snapshot.budget_available:
                        continue
                    checks = self.github.required_statuses(repository_id, sha, target.required)
                    state = replace(target.snapshot, observed_sha=sha, checks=checks)
                    decision = decide(state)
                    self.outbox.record(target, decision, checks)
                self.inbox.acknowledge(delivery)
                processed += 1
            except Exception:
                # No acknowledgement on failure. Durable deduplication permits replay.
                failed += 1
        return {"processed": processed, "failed": failed}
