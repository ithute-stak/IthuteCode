"""Webhook ingestion: notifications are hints, never authoritative CI evidence."""
import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass

@dataclass(frozen=True)
class Notice:
    repository_id: int
    sha: str

def authenticate_notice(body: bytes, signature: str, event: str, secret: bytes,
                        allowed_repositories: frozenset[int]) -> Notice | None:
    if not secret or len(body) > 2_000_000:
        raise ValueError("Invalid webhook configuration or size")
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not signature.isascii() or not hmac.compare_digest(expected, signature):
        raise PermissionError("Invalid webhook signature")
    if event not in {"workflow_run", "check_run", "check_suite"}:
        return None
    data = json.loads(body)
    if data.get("action") != "completed":
        return None
    repo_id = data["repository"]["id"]
    if type(repo_id) is not int or repo_id not in allowed_repositories:
        raise PermissionError("Repository not authorized")
    sha = data[event]["head_sha"]
    if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid commit SHA")
    return Notice(repo_id, sha)

class Inbox:
    """Durable notification queue; a future worker reconciles GitHub state."""
    def __init__(self, path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Durable path required")
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS github_inbox (
                delivery TEXT PRIMARY KEY, repository_id INTEGER NOT NULL,
                sha TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0
            )""")

    def enqueue(self, delivery: str, notice: Notice) -> bool:
        if not isinstance(delivery, str) or not delivery.strip() or len(delivery) > 128:
            raise ValueError("Invalid delivery ID")
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT OR IGNORE INTO github_inbox(delivery,repository_id,sha) VALUES (?,?,?)",
                             (delivery, notice.repository_id, notice.sha))
            return cur.rowcount == 1

    def pending(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT delivery,repository_id,sha FROM github_inbox WHERE processed=0 ORDER BY rowid LIMIT 100").fetchall()

    def acknowledge(self, delivery):
        # Only call after reconciliation state has been durably recorded.
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE github_inbox SET processed=1 WHERE delivery=?", (delivery,))
