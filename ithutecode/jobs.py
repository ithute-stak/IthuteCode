"""Persistent single-project execution leases.

Expired jobs require explicit reconciliation before retry: a remote push or
billable AI request may already have happened. This queue does not itself
authorize external side effects.
"""
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager

class JobQueue:
    def __init__(self, path, clock=time.time):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Durable database required")
        self.clock = clock
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS coding_jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                lease TEXT, expires REAL, result TEXT,
                attempts INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_active_coding_job
                ON coding_jobs(project_id) WHERE status IN ('running','uncertain')""")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, job_id, project_id, payload):
        if not all(isinstance(v, str) and v.strip() and len(v) <= 200 for v in (job_id, project_id)):
            raise ValueError("Invalid job identity")
        if not isinstance(payload, dict):
            raise ValueError("Job payload must be an object")
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 200_000:
            raise ValueError("Job payload too large")
        with self.transaction() as db:
            row = db.execute("SELECT project_id,payload FROM coding_jobs WHERE id=?", (job_id,)).fetchone()
            if row:
                if (row["project_id"], row["payload"]) != (project_id, encoded):
                    raise ValueError("Job identity collision")
                return False
            db.execute("INSERT INTO coding_jobs(id,project_id,payload) VALUES (?,?,?)",
                       (job_id, project_id, encoded))
            return True

    def claim(self, lease_seconds=300):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        with self.transaction() as db:
            now = self.clock()
            db.execute("UPDATE coding_jobs SET status='uncertain' WHERE status='running' AND expires<=?", (now,))
            row = db.execute("""SELECT j.* FROM coding_jobs j WHERE j.status='queued'
                AND NOT EXISTS (SELECT 1 FROM coding_jobs a WHERE a.project_id=j.project_id
                AND a.status IN ('running','uncertain')) ORDER BY j.rowid LIMIT 1""").fetchone()
            if row is None:
                return None
            lease = secrets.token_hex(32)
            db.execute("""UPDATE coding_jobs SET status='running',lease=?,expires=?,attempts=attempts+1
                WHERE id=?""", (lease, now+lease_seconds, row["id"]))
            return {"id":row["id"], "project_id":row["project_id"], "payload":json.loads(row["payload"]),
                    "lease":lease, "attempts":row["attempts"]+1}

    def finish(self, job_id, lease, result):
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 200_000:
            raise ValueError("Result too large")
        with self.transaction() as db:
            changed = db.execute("""UPDATE coding_jobs SET status='completed',result=?,lease=NULL,expires=NULL
                WHERE id=? AND lease=? AND status='running' AND expires>?""",
                (encoded, job_id, lease, self.clock())).rowcount
            if changed != 1:
                raise PermissionError("Invalid or expired execution lease")

    def reconcile(self, job_id, lease, outcome, evidence):
        """Trusted operator only, after verifying old worker stopped and external effects."""
        if outcome not in {"completed","failed"} or not isinstance(evidence,str) or not evidence.strip():
            raise ValueError("Explicit reconciliation evidence required")
        with self.transaction() as db:
            changed = db.execute("""UPDATE coding_jobs SET status=?,result=?,lease=NULL,expires=NULL
                WHERE id=? AND lease=? AND status='uncertain'""",
                (outcome,json.dumps({"evidence":evidence}),job_id,lease)).rowcount
            if changed != 1:
                raise PermissionError("Job not eligible for reconciliation")

    def status(self, job_id):
        with self.transaction() as db:
            row = db.execute("SELECT status,attempts FROM coding_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return dict(row)

    def active(self, job_id, lease):
        with self.transaction() as db:
            return db.execute("""SELECT 1 FROM coding_jobs WHERE id=? AND lease=?
                AND status='running' AND expires>?""", (job_id,lease,self.clock())).fetchone() is not None

    def defer(self, job_id, lease):
        """Return an untouched job to the queue; only before any side effect."""
        with self.transaction() as db:
            changed = db.execute("""UPDATE coding_jobs SET status='queued',lease=NULL,expires=NULL
                WHERE id=? AND lease=? AND status='running' AND expires>?""",
                (job_id,lease,self.clock())).rowcount
            if changed != 1:
                raise PermissionError("Invalid or expired execution lease")

    def mark_uncertain(self, job_id, lease):
        """Freeze project execution when an external outcome is unknown."""
        with self.transaction() as db:
            changed = db.execute("""UPDATE coding_jobs SET status='uncertain'
                WHERE id=? AND lease=? AND status IN ('running','uncertain')""",
                (job_id,lease)).rowcount
            if changed != 1:
                raise PermissionError("Invalid execution lease")
