"""Strict JSON bridge for the future structured coding provider."""
import json
from .patch_policy import Edit, validate_edits

def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result

def parse_proposal(raw: str, allowed_paths: frozenset[str]) -> tuple[Edit, ...]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 250_000:
        raise ValueError("Invalid proposal size")
    data = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(data, dict) or set(data) != {"edits"} or not isinstance(data["edits"], list):
        raise ValueError("Expected edits object")
    edits = []
    for item in data["edits"]:
        if not isinstance(item, dict) or set(item) != {"path", "expected_sha256", "content"}:
            raise ValueError("Invalid edit schema")
        edits.append(Edit(**item))
    return validate_edits(tuple(edits), allowed_paths)
