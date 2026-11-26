"""Pure CI reconciliation. Input must come from authenticated GitHub API pagination."""
from dataclasses import dataclass

@dataclass(frozen=True)
class RequiredCheck:
    name: str
    app_id: int

def reconcile(candidate_sha: str, required: tuple[RequiredCheck, ...], runs: list[dict]) -> dict[str, str]:
    if len(candidate_sha) != 40 or any(c not in "0123456789abcdef" for c in candidate_sha):
        raise ValueError("Invalid candidate SHA")
    if not required or len({c.name for c in required}) != len(required):
        raise ValueError("Nonempty unique required check names expected")
    result = {}
    for check in required:
        matching = [r for r in runs if r.get("head_sha") == candidate_sha
                    and r.get("name") == check.name
                    and (r.get("app") or {}).get("id") == check.app_id]
        if not matching:
            result[check.name] = "missing"
            continue
        # Ambiguous duplicate runs must not create false green results.
        if len(matching) != 1:
            result[check.name] = "ambiguous"
            continue
        run = matching[0]
        result[check.name] = (run.get("conclusion") or "pending") if run.get("status") == "completed" else "pending"
    return result
