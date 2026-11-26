"""Recover confirmed remote writes only after trusted worker fencing.

A baseline or divergent remote head is not proof that a push never happened.
Those cases remain blocked. No AI request or Git push is issued here.
"""
import json
from .publisher import Publication

class PublicationRecovery:
    def __init__(self, milestones, authorize, worker_stopped, remote_head, resolve_ordinal):
        self.milestones = milestones
        self.queue = milestones.queue
        self.authorize = authorize
        self.worker_stopped = worker_stopped
        self.remote_head = remote_head
        self.resolve_ordinal = resolve_ordinal

    def recover(self, job_id):
        with self.queue.transaction() as db:
            row = db.execute("""SELECT j.*, p.publication FROM coding_jobs j
                JOIN publication_journal p ON p.job_id=j.id
                WHERE j.id=? AND j.status='uncertain'""",(job_id,)).fetchone()
            if row is None:
                return "not_eligible"
            claimed = {"id":row["id"],"project_id":row["project_id"],
                       "lease":row["lease"],"payload":json.loads(row["payload"])}
            publication = Publication(**json.loads(row["publication"]))
        if not self.authorize(claimed,publication) or not self.worker_stopped(claimed):
            return "blocked"
        if self.remote_head(publication.repository_id,publication.branch) != publication.commit_sha:
            return "blocked"
        ordinal = self.resolve_ordinal(claimed,publication)
        if not self.authorize(claimed,publication) or not self.worker_stopped(claimed):
            return "blocked"
        self.milestones._record(claimed,publication,ordinal,recovery=True)
        return "recovered"
