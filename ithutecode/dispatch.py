"""Dispatch only freshly authorized decisions; execution must reauthorize.

Outbox and queue must share the same SQLite database. No external side
effects are performed here. Authorization resolver must use trusted state.
"""
import hashlib
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class PendingDecision:
    project_id: str
    ordinal: int
    sha: str
    decision: str
    attempt: int

class Dispatcher:
    def __init__(self, queue, resolve):
        self.queue = queue
        self.resolve = resolve
        with queue.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS dispatched_decisions (
                project_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                sha TEXT NOT NULL, decision TEXT NOT NULL,
                attempt INTEGER NOT NULL, job_id TEXT NOT NULL,
                PRIMARY KEY(project_id,ordinal,sha,decision,attempt)
            )""")

    def run_once(self):
        with self.queue.transaction() as db:
            rows = db.execute("""SELECT o.project_id,o.ordinal,o.sha,o.decision,o.attempt
                FROM decision_outbox o WHERE NOT EXISTS (
                    SELECT 1 FROM dispatched_decisions d WHERE
                    d.project_id=o.project_id AND d.ordinal=o.ordinal AND
                    d.sha=o.sha AND d.decision=o.decision AND d.attempt=o.attempt)
                ORDER BY o.rowid LIMIT 100""").fetchall()
        dispatched = deferred = 0
        for row in rows:
            decision = PendingDecision(*tuple(row))
            if decision.decision not in {"repair","review","next_task","approval"}:
                deferred += 1
                continue
            # A trusted resolver must recheck current commit, task, CI, policy,
            # pause and budget. None means not currently eligible.
            payload = self.resolve(decision)
            if payload is None:
                deferred += 1
                continue
            if not isinstance(payload, dict):
                raise ValueError("Resolver must return a job object")
            envelope = {"decision":dict(zip(
                ("project_id","ordinal","sha","decision","attempt"),tuple(row))),
                "job":payload}
            identity = hashlib.sha256(json.dumps(envelope["decision"],sort_keys=True).encode()).hexdigest()
            # Separate transactions are intentional: enqueue is idempotent,
            # so a crash before recording the dispatch can replay safely.
            self.queue.enqueue(identity, decision.project_id, envelope)
            with self.queue.transaction() as db:
                changed = db.execute("INSERT OR IGNORE INTO dispatched_decisions VALUES (?,?,?,?,?,?)",
                                     (*tuple(row),identity)).rowcount
            dispatched += changed
        return {"dispatched":dispatched,"deferred":deferred}
