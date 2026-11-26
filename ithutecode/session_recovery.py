"""Reconcile interrupted AI sessions using authenticated provider evidence.

No provider request is replayed. Unknown costs and outcomes remain blocked.
The trusted runtime must bind provider evidence to the exact request digest.
"""
from dataclasses import dataclass, asdict
import json
import hashlib

@dataclass(frozen=True)
class SessionEvidence:
    session_id: str
    project_id: str
    request_digest: str
    provider_reference: str
    outcome: str
    input_tokens: int
    output_tokens: int
    actual_units: int

class SessionRecovery:
    def __init__(self, sessions, authenticate, worker_stopped):
        self.store = sessions.store
        self.authenticate = authenticate
        self.worker_stopped = worker_stopped
        with self.store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ai_session_reconciliations (
                session_id TEXT PRIMARY KEY REFERENCES ai_sessions(id),
                provider_reference TEXT NOT NULL UNIQUE,
                evidence TEXT NOT NULL,
                digest TEXT NOT NULL
            )""")

    def reconcile(self, evidence):
        if not isinstance(evidence, SessionEvidence):
            raise ValueError("Structured provider evidence required")
        if evidence.outcome not in {"completed","failed","not_submitted"}:
            raise ValueError("Unknown provider outcome")
        if not isinstance(evidence.provider_reference,str) or not evidence.provider_reference.strip():
            raise ValueError("Provider evidence reference required")
        for n in (evidence.input_tokens,evidence.output_tokens,evidence.actual_units):
            if type(n) is not int or not 0 <= n <= 10**12:
                raise ValueError("Invalid usage evidence")
        if evidence.outcome == "not_submitted" and any(
            (evidence.input_tokens,evidence.output_tokens,evidence.actual_units)):
            raise ValueError("Unsubmitted request cannot have usage")
        record = json.dumps(asdict(evidence),sort_keys=True)
        if len(record.encode()) > 24000:
            raise ValueError("Evidence exceeds bound")
        if not self.authenticate(evidence) or not self.worker_stopped(evidence.session_id):
            raise PermissionError("Authenticated evidence and stopped worker required")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM ai_sessions WHERE id=?",(evidence.session_id,)).fetchone()
            if row is None or (row["project_id"],row["request_digest"]) != (
                evidence.project_id,evidence.request_digest):
                raise PermissionError("Session identity mismatch")
            old = db.execute("SELECT evidence FROM ai_session_reconciliations WHERE session_id=?",
                             (evidence.session_id,)).fetchone()
            if old:
                if old["evidence"] != record:
                    raise PermissionError("Conflicting reconciliation")
                return "reconciled"
            if row["status"] not in {"started","uncertain"}:
                raise PermissionError("Session is not interrupted")
            if db.execute("SELECT 1 FROM ai_session_reconciliations WHERE provider_reference=?",
                          (evidence.provider_reference,)).fetchone():
                raise PermissionError("Provider evidence already used")
            db.execute("INSERT INTO ai_session_reconciliations VALUES (?,?,?,?)",
                       (evidence.session_id,evidence.provider_reference,record,
                        hashlib.sha256(record.encode()).hexdigest()))
            db.execute("UPDATE ai_sessions SET status='reconciled' WHERE id=?",
                       (evidence.session_id,))
        return "reconciled"
