"""Commit-bound milestone recording in the shared SQLite prototype.

Publication is not acceptance. A milestone requires a current execution lease,
a confirmed journal entry and an independently observed remote head.
"""
import hashlib
import json
from pathlib import Path

class Milestones:
    def __init__(self, checkpoints, journal, verify_head):
        self.checkpoints = checkpoints
        self.store = checkpoints.store
        self.queue = journal.queue
        self.verify_head = verify_head
        if Path(self.store.path).resolve() != Path(self.queue.path).resolve():
            raise ValueError("Milestones require a shared database")
        with self.store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS publication_milestones (
                job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL, sha TEXT NOT NULL,
                sequence INTEGER NOT NULL
            )""")

    def record(self, claimed, publication, ordinal):
        return self._record(claimed, publication, ordinal, recovery=False)

    def _record(self, claimed, publication, ordinal, *, recovery):
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError("Invalid task ordinal")
        project = publication.project_id
        sha = publication.commit_sha
        if project != claimed["project_id"]:
            raise PermissionError("Project mismatch")
        if not self.verify_head(publication.repository_id, publication.branch, sha):
            raise PermissionError("Remote head mismatch")
        with self.store.transaction() as db:
            row = db.execute("""SELECT project_id,payload,status,expires FROM coding_jobs
                WHERE id=? AND lease=?""", (claimed["id"],claimed["lease"])).fetchone()
            if row is not None and (row["status"] != ("uncertain" if recovery else "running") or
                (not recovery and row["expires"] <= self.queue.clock())):
                row = None
            if row is None or row["project_id"] != project:
                raise PermissionError("Milestone lease invalid")
            decision = json.loads(row["payload"])["decision"]
            if decision["project_id"] != project or decision["sha"] != publication.baseline_sha:
                raise PermissionError("Publication baseline mismatch")
            journal = db.execute("SELECT * FROM publication_journal WHERE job_id=?",
                                 (claimed["id"],)).fetchone()
            from dataclasses import asdict
            if journal is None or journal["status"] not in (("intent","published") if recovery else ("published",)) or journal["project_id"] != project or json.loads(journal["publication"]) != asdict(publication):
                raise PermissionError("Confirmed publication required")
            if recovery:
                db.execute("UPDATE publication_journal SET status='published' WHERE job_id=?", (claimed["id"],))
            task = self.store._active(db,project,ordinal)
            old = db.execute("SELECT * FROM publication_milestones WHERE job_id=?",
                             (claimed["id"],)).fetchone()
            if old:
                if (old["project_id"],old["ordinal"],old["sha"],task["candidate_sha"]) != (project,ordinal,sha,sha):
                    raise PermissionError("Conflicting milestone")
                if recovery:
                    self._finish_recovery(db,claimed,sha)
                return old["sequence"]
            if task["candidate_sha"] not in (None,publication.baseline_sha):
                raise PermissionError("Stale task baseline")
            db.execute("UPDATE tasks SET candidate_sha=? WHERE project_id=? AND ordinal=?",
                       (sha,project,ordinal))
            state = self.checkpoints._state(db,project)
            payload = json.dumps({"state":state,"sha":sha,"untrusted_notes":
                "Candidate published; independent CI and review are still required."},sort_keys=True)
            if len(payload.encode()) > 200000:
                raise ValueError("Checkpoint exceeds storage bound")
            seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM development_checkpoints WHERE project_id=?",
                             (project,)).fetchone()[0]
            db.execute("INSERT INTO development_checkpoints VALUES (?,?,?,?,?)",
                       (project,seq,sha,payload,hashlib.sha256(payload.encode()).hexdigest()))
            db.execute("INSERT INTO publication_milestones VALUES (?,?,?,?,?)",
                       (claimed["id"],project,ordinal,sha,seq))
            if recovery:
                self._finish_recovery(db,claimed,sha)
            return seq

    @staticmethod
    def _finish_recovery(db, claimed, sha):
        changed = db.execute("""UPDATE coding_jobs SET status='completed',lease=NULL,expires=NULL,result=?
            WHERE id=? AND lease=? AND status='uncertain'""",
            (json.dumps({"outcome":"recovered_publication","commit_sha":sha}),claimed["id"],claimed["lease"])).rowcount
        if changed != 1:
            raise PermissionError("Recovery lease changed")
