"""Durable recovery context; generated notes never confer authorization."""
import hashlib
import json
import re

class Checkpoints:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS development_checkpoints (
                project_id TEXT NOT NULL REFERENCES projects(id),
                sequence INTEGER NOT NULL, sha TEXT NOT NULL,
                snapshot TEXT NOT NULL, digest TEXT NOT NULL,
                PRIMARY KEY(project_id,sequence)
            )""")

    def _state(self, db, project_id):
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise KeyError(project_id)
        tasks = db.execute("""SELECT ordinal,requirement,candidate_sha,verified_sha
            FROM tasks WHERE project_id=? ORDER BY ordinal""", (project_id,)).fetchall()
        return {"project":dict(project),"tasks":[dict(t) for t in tasks]}

    def save(self, project_id, sha, notes, verify_head):
        if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
            raise ValueError("Exact commit required")
        if not isinstance(notes,str) or len(notes.encode()) > 24000:
            raise ValueError("Invalid or oversized notes")
        if not verify_head(project_id,sha):
            raise PermissionError("Checkpoint does not match verified repository head")
        with self.store.transaction() as db:
            state = self._state(db,project_id)
            payload = json.dumps({"state":state,"sha":sha,"untrusted_notes":notes},sort_keys=True)
            if len(payload.encode()) > 200000:
                raise ValueError("Checkpoint exceeds storage bound")
            digest = hashlib.sha256(payload.encode()).hexdigest()
            seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM development_checkpoints WHERE project_id=?",
                             (project_id,)).fetchone()[0]
            db.execute("INSERT INTO development_checkpoints VALUES (?,?,?,?,?)",
                       (project_id,seq,sha,payload,digest))
            return seq

    def recover(self, project_id, sha, verify_head):
        """Recover only current state and notes tied to the same verified head.
        Old checkpoints are retained for audit, not used as current authority.
        """
        if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
            raise ValueError("Exact commit required")
        if not verify_head(project_id,sha):
            raise PermissionError("Recovery head mismatch")
        with self.store.transaction() as db:
            state = self._state(db,project_id)
            row = db.execute("""SELECT * FROM development_checkpoints
                WHERE project_id=? ORDER BY sequence DESC LIMIT 1""",(project_id,)).fetchone()
            notes = ""
            sequence = None
            if row is not None and row["sha"] == sha:
                raw = row["snapshot"]
                if hashlib.sha256(raw.encode()).hexdigest() != row["digest"]:
                    raise RuntimeError("Checkpoint integrity failure")
                saved = json.loads(raw)
                if saved["sha"] != sha or saved["state"]["project"]["id"] != project_id:
                    raise RuntimeError("Checkpoint identity mismatch")
                if saved["state"] == state:
                    notes = saved["untrusted_notes"]
                    sequence = row["sequence"]
            return {"state":state,"sha":sha,"untrusted_notes":notes,"sequence":sequence}
