"""One coding handler. Trusted runtime supplies policy, budget and durable journal.
No repository code execution. Publication intent must be persisted before push.
"""
from dataclasses import dataclass
from .pipeline import CodingPipeline, CodingJob
from .publisher import Publisher, Publication
from .provision import provision
from .git_transport import GitTransport

@dataclass(frozen=True)
class CodingPlan:
    repository_id: int
    remote: str
    job: CodingJob

class CodingHandler:
    def __init__(self, parent, agent, resolve_plan, reserve_budget,
                 verify_commit, journal, token_provider=None, *, local_test=False):
        self.parent = parent
        self.agent = agent
        self.resolve_plan = resolve_plan
        self.reserve_budget = reserve_budget
        self.verify_commit = verify_commit
        self.journal = journal
        self.token_provider = token_provider
        self.local_test = local_test

    def __call__(self, claimed, guard):
        guard()
        decision = claimed["payload"]["decision"]
        plan = self.resolve_plan(claimed)
        job = plan.job
        req = job.request
        expected_mode = {"repair":"repair", "next_task":"implement"}.get(decision["decision"])
        if expected_mode is None or req.mode != expected_mode:
            raise PermissionError("Unexpected coding mode")
        if req.project_id != claimed["project_id"] or req.candidate_sha != decision["sha"]:
            raise PermissionError("Stale or mismatched coding plan")
        guard()
        with provision(self.parent, plan.remote, req.candidate_sha, job.branch,
                       local_test=self.local_test, repository_id=plan.repository_id,
                       token_provider=self.token_provider) as root:
            transport = GitTransport(root, plan.repository_id, plan.remote,
                                     local_test=self.local_test, token_provider=self.token_provider)
            def authorized(*args):
                guard()
                return True
            guard()
            transport.initialize_branch(plan.repository_id, job.branch, req.candidate_sha, authorized)
            guard()
            self.reserve_budget(claimed)
            guard()
            result = CodingPipeline(self.agent, authorized).run(root, job)
            publication = Publication(req.project_id, plan.repository_id, job.branch,
                                      req.candidate_sha, result.commit_sha)
            guard()
            self.journal.record_intent(claimed, publication)
            published = Publisher(transport, authorized,
                                  lambda p: self.verify_commit(root, p, job)).publish(publication)
            guard()
            self.journal.record_published(claimed, publication)
            return {"outcome":"published", "commit_sha":published, "branch":job.branch}
