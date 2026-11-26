"""Read-only GitHub REST adapter. Credentials are injected at runtime."""
import json
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .ci import reconcile

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class GitHubClient:
    def __init__(self, token_provider, transport=None, max_pages=20):
        if not 1 <= max_pages <= 100:
            raise ValueError("Invalid page limit")
        self.token_provider = token_provider
        self.transport = transport or self._request
        self.max_pages = max_pages

    @staticmethod
    def _request(url, token):
        req = Request(url, headers={"Authorization": "Bearer " + token,
                      "Accept": "application/vnd.github+json",
                      "X-GitHub-Api-Version": "2022-11-28"})
        with build_opener(NoRedirect()).open(req, timeout=15) as response:
            payload = response.read(8_000_001)
            if len(payload) > 8_000_000:
                raise ValueError("GitHub response too large")
            return json.loads(payload)

    def check_runs(self, repository_id, sha):
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("Invalid repository ID")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid commit SHA")
        token = self.token_provider(repository_id)
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError("Invalid GitHub credential")
        runs = []
        expected = None
        ids = set()
        for page in range(1, self.max_pages + 1):
            url = f"https://api.github.com/repositories/{repository_id}/commits/{sha}/check-runs?filter=latest&per_page=100&page={page}"
            data = self.transport(url, token)
            batch, total = data["check_runs"], data["total_count"]
            if type(total) is not int or total < 0 or not isinstance(batch, list) or len(batch) > 100:
                raise ValueError("Invalid check response")
            if expected is None:
                expected = total
            if total != expected:
                raise RuntimeError("Check collection changed during pagination")
            for run in batch:
                identifier = run["id"]
                if type(identifier) is not int or identifier in ids:
                    raise RuntimeError("Duplicate or invalid check run")
                ids.add(identifier)
                runs.append(run)
            if len(runs) == expected:
                return runs
            if len(runs) > expected or len(batch) < 100:
                raise RuntimeError("Incomplete check collection")
        raise RuntimeError("Check pagination limit exceeded")

    def required_statuses(self, repository_id, sha, required):
        return reconcile(sha, required, self.check_runs(repository_id, sha))
