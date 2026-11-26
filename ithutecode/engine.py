"""Pure decision core; external workers must enforce authorization and persistence."""
from dataclasses import dataclass
from enum import Enum

class Decision(str, Enum):
    WAIT = "wait"
    REPAIR = "repair"
    NEXT_TASK = "next_task"
    REVIEW = "review"
    APPROVAL = "approval"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class Snapshot:
    candidate_sha: str
    observed_sha: str
    required_checks: tuple[str, ...]
    checks: dict[str, str]
    task_verified: bool = False
    remaining_tasks: int = 1
    repair_attempts: int = 0
    max_repairs: int = 3
    budget_available: bool = True
    paused: bool = False

def decide(state: Snapshot) -> Decision:
    if state.paused or not state.budget_available:
        return Decision.BLOCKED
    if state.remaining_tasks < 0 or state.repair_attempts < 0 or state.max_repairs < 0:
        return Decision.BLOCKED
    if not state.candidate_sha or state.candidate_sha != state.observed_sha:
        return Decision.WAIT
    if not state.required_checks:
        return Decision.BLOCKED
    statuses = [state.checks.get(name, "missing") for name in state.required_checks]
    if any(status in {"failure", "timed_out", "action_required", "cancelled"} for status in statuses):
        return Decision.REPAIR if state.repair_attempts < state.max_repairs else Decision.BLOCKED
    if any(status != "success" for status in statuses):
        return Decision.WAIT
    if not state.task_verified:
        return Decision.REVIEW
    return Decision.NEXT_TASK if state.remaining_tasks else Decision.APPROVAL
