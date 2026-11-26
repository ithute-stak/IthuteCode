"""Local durable prototype. PostgreSQL and authenticated workers are future adapters."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class ProjectStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("A durable database path is required")
        with self.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, instruction TEXT NOT NULL,
                repository TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tasks (
                project_id TEXT NOT NULL REFERENCES projects(id),
                ordinal INTEGER NOT NULL, requirement TEXT NOT NULL,
                candidate_sha TEXT, verified_sha TEXT, evidence TEXT,
                PRIMARY KEY(project_id, ordinal)
            );
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_project(self, project_id, repository, instruction, requirements):
        requirements = tuple(requirements)
        if not all(isinstance(x, str) and x.strip() for x in
                   (project_id, repository, instruction, *requirements)) or not requirements:
            raise ValueError("Project and nonempty requirements are mandatory")
        with self.transaction() as db:
            db.execute("INSERT INTO projects(id,repository,instruction) VALUES (?,?,?)",
                       (project_id, repository, instruction))
            db.executemany("INSERT INTO tasks(project_id,ordinal,requirement) VALUES (?,?,?)",
                           [(project_id, i, req) for i, req in enumerate(requirements)])

    def next_task(self, project_id):
        with self.transaction() as db:
            project = db.execute("SELECT paused FROM projects WHERE id=?", (project_id,)).fetchone()
            if project is None:
                raise KeyError(project_id)
            if project["paused"]:
                return None
            row = db.execute("""SELECT * FROM tasks WHERE project_id=?
                AND verified_sha IS NULL ORDER BY ordinal LIMIT 1""", (project_id,)).fetchone()
            return dict(row) if row else None

    def set_paused(self, project_id, paused):
        with self.transaction() as db:
            if db.execute("UPDATE projects SET paused=? WHERE id=?", (int(bool(paused)), project_id)).rowcount != 1:
                raise KeyError(project_id)

    def _active(self, db, project_id, ordinal):
        row = db.execute("""SELECT t.* FROM tasks t JOIN projects p ON p.id=t.project_id
            WHERE t.project_id=? AND p.paused=0 AND t.verified_sha IS NULL
            ORDER BY ordinal LIMIT 1""", (project_id,)).fetchone()
        if row is None or row["ordinal"] != ordinal:
            raise ValueError("Task is not active")
        return row

    def record_candidate(self, project_id, ordinal, sha):
        if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Expected full lowercase Git commit SHA")
        with self.transaction() as db:
            self._active(db, project_id, ordinal)
            db.execute("UPDATE tasks SET candidate_sha=? WHERE project_id=? AND ordinal=?",
                       (sha, project_id, ordinal))

    def accept(self, project_id, ordinal, sha, evidence):
        # Internal persistence operation only: caller must independently verify CI and reviewer authority.
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("Acceptance evidence is required")
        with self.transaction() as db:
            row = self._active(db, project_id, ordinal)
            if not sha or row["candidate_sha"] != sha:
                raise ValueError("Stale or missing candidate")
            db.execute("UPDATE tasks SET verified_sha=?, evidence=? WHERE project_id=? AND ordinal=?",
                       (sha, evidence, project_id, ordinal))

    def progress(self, project_id):
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise KeyError(project_id)
            row = db.execute("SELECT COUNT(*), COUNT(verified_sha) FROM tasks WHERE project_id=?",
                             (project_id,)).fetchone()
            return {"total": row[0], "verified": row[1]}
