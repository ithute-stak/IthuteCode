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

## Architecture
Python orchestration core, persistent PostgreSQL state, authenticated GitHub webhooks and reconciliation, isolated coding workers, and an eventual React dashboard. Provider integrations must be replaceable.

## Status
Initial foundation only. No live AI worker, GitHub webhook, or deployment is configured yet.

## Local tests
`python -m unittest discover -s tests -v`
