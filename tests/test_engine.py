import unittest
from dataclasses import replace
from ithutecode.engine import Snapshot, Decision, decide

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.state = Snapshot("abc", "abc", ("test", "security"), {"test": "success", "security": "success"})

    def test_green_requires_review(self):
        self.assertEqual(decide(self.state), Decision.REVIEW)

    def test_verified_advances(self):
        self.assertEqual(decide(replace(self.state, task_verified=True)), Decision.NEXT_TASK)

    def test_completion_requires_approval(self):
        self.assertEqual(decide(replace(self.state, task_verified=True, remaining_tasks=0)), Decision.APPROVAL)

    def test_stale_commit_waits(self):
        self.assertEqual(decide(replace(self.state, observed_sha="old")), Decision.WAIT)

    def test_missing_check_waits(self):
        self.assertEqual(decide(replace(self.state, checks={"test": "success"})), Decision.WAIT)

    def test_no_required_checks_blocks(self):
        self.assertEqual(decide(replace(self.state, required_checks=())), Decision.BLOCKED)

    def test_failure_repairs(self):
        self.assertEqual(decide(replace(self.state, checks={"test": "failure"})), Decision.REPAIR)

    def test_retry_limit_blocks(self):
        self.assertEqual(decide(replace(self.state, checks={"test": "failure"}, repair_attempts=3)), Decision.BLOCKED)

    def test_budget_and_pause(self):
        for state in (replace(self.state, budget_available=False), replace(self.state, paused=True)):
            self.assertEqual(decide(state), Decision.BLOCKED)

    def test_skipped_is_not_success(self):
        self.assertEqual(decide(replace(self.state, checks={"test": "success", "security": "skipped"})), Decision.WAIT)

if __name__ == "__main__":
    unittest.main()
