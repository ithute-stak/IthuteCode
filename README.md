# IthuteCode

Code. Test. Fix. Repeat.

Autonomous software engineering orchestration for GitHub and OpenAI coding agents.

## Initial acceptance criteria
- Persist project requirements and ordered tasks.
- Run coding agents in isolated workspaces on non-production branches.
- Verify every configured required CI check for the exact candidate commit; missing checks never count as success.
- Repair failed checks within a bounded retry and budget policy.
- Advance only after independent task acceptance and passing CI.
- Stop for approval when every agreed requirement is verified, or when blocked.
- Never automatically merge, deploy, expose secrets, or weaken verification.

## Mandatory AI continuity requirements
- Persist original instructions, acceptance criteria, decisions, unfinished tasks and commit-bound checkpoints outside AI sessions.
- Start fresh bounded AI sessions when context is exhausted; reconstruct relevant context from trusted durable state and exact repository revisions.
- Never treat a generated summary as authoritative acceptance evidence.
- Recover after restart without repeating uncertain billable requests or remote writes.
- Enforce token and expenditure budgets across session rotations; stop on quota or unresolved blockers.
- Verify continuity with tests that rotate sessions mid-project and preserve task identity, security policies and verified progress.

## Architecture
Python orchestration core, persistent PostgreSQL state, authenticated GitHub webhooks and reconciliation, isolated coding workers, and an eventual React dashboard. Provider integrations must be replaceable.

## Status
Initial foundation only. No live AI worker, GitHub webhook, or deployment is configured yet.

## Local tests
`python -m unittest discover -s tests -v`
