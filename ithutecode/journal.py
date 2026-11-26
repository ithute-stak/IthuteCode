"""Durable publication journal sharing the execution queue database."""
import json
import re
from dataclasses import asdict

class PublicationJournal:
    def __init__(self, queue):
        self.queue = queue
        with queue.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS publication_journal (
                job_id TEXT PRIMARY KEY REFERENCES coding_jobs(id),
                project_id TEXT NOT NULL,
                publication TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('intent','published'))
            )""")

    def _check(self, db, claimed, publication):
        row = db.execute("""SELECT project_id FROM coding_jobs WHERE id=? AND lease=?
            AND status='running' AND expires>?""",
            (claimed["id"], claimed["lease"], self.queue.clock())).fetchone()
        if row is None or row["project_id"] != claimed["project_id"] or publication.project_id != row["project_id"]:
            raise PermissionError("Publication lease or project mismatch")
        if type(publication.repository_id) is not int or publication.repository_id <= 0:
            raise ValueError("Invalid repository")
        if not re.fullmatch(r"ithutecode/[a-z0-9][a-z0-9-]{0,79}", publication.branch):
            raise ValueError("Invalid development branch")
        for sha in (publication.baseline_sha, publication.commit_sha):
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("Invalid publication SHA")
        if publication.baseline_sha == publication.commit_sha:
            raise ValueError("Unchanged publication")
        return json.dumps(asdict(publication), sort_keys=True)

    def record_intent(self, claimed, publication):
        with self.queue.transaction() as db:
            encoded = self._check(db, claimed, publication)
            row = db.execute("SELECT publication,status FROM publication_journal WHERE job_id=?",
                             (claimed["id"],)).fetchone()
            if row:
                # Never grant permission to repeat an uncertain remote write.
                raise RuntimeError("Publication already recorded; reconcile before retry")
            db.execute("INSERT INTO publication_journal VALUES (?,?,?,'intent')",
                       (claimed["id"], claimed["project_id"], encoded))

    def record_published(self, claimed, publication):
        with self.queue.transaction() as db:
            encoded = self._check(db, claimed, publication)
            changed = db.execute("""UPDATE publication_journal SET status='published'
                WHERE job_id=? AND publication=? AND status='intent'""",
                (claimed["id"], encoded)).rowcount
            if changed != 1:
                raise RuntimeError("Missing or mismatched publication intent")

    def inspect(self, job_id):
        with self.queue.transaction() as db:
            row = db.execute("SELECT * FROM publication_journal WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                return None
            return {"job_id":row["job_id"], "project_id":row["project_id"],
                    "publication":json.loads(row["publication"]), "status":row["status"]}
