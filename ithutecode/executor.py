"""Trusted handler dispatch; handlers must guard every external side effect."""
from threading import Event

class Executor:
    def __init__(self, queue, authorize, handlers, lease_seconds=900):
        self.queue = queue
        self.authorize = authorize
        self.handlers = dict(handlers)
        self.lease_seconds = lease_seconds

    def run_once(self):
        job = self.queue.claim(self.lease_seconds)
        if job is None:
            return "idle"
        job_id, lease = job["id"], job["lease"]

        def guard():
            if not self.queue.active(job_id, lease) or not self.authorize(job):
                raise PermissionError("Execution authorization or lease lost")

        try:
            payload = job["payload"]
            decision = payload["decision"]
            if decision["project_id"] != job["project_id"]:
                raise ValueError("Project identity mismatch")
            kind = decision["decision"]
            handler = self.handlers.get(kind) if kind in {"repair", "review", "next_task", "approval"} else None
            if handler is None:
                self.queue.finish(job_id, lease, {"outcome":"unsupported"})
                return "unsupported"
            if not self.authorize(job):
                self.queue.defer(job_id, lease)
                return "deferred"
            guard()
            result = handler(job, guard)
            guard()
            if not isinstance(result, dict):
                raise ValueError("Handler must return structured result")
            self.queue.finish(job_id, lease, result)
            return "completed"
        except Exception:
            # Even an exception can follow a successful external operation.
            # Do not silently replay billable requests or remote writes.
            self.queue.mark_uncertain(job_id, lease)
            return "uncertain"

class ServiceLoop:
    def __init__(self, stages, interval=5):
        if not isinstance(interval, (int, float)) or not 0.1 <= interval <= 300:
            raise ValueError("Invalid polling interval")
        self.stages = tuple(stages)
        self.interval = interval

    def tick(self, stop=None):
        results = []
        for stage in self.stages:
            if stop is not None and stop.is_set():
                break
            results.append(stage.run_once())
        return results

    def run(self, stop: Event):
        """Supervisor should restart on infrastructure exceptions."""
        while not stop.is_set():
            self.tick(stop)
            stop.wait(self.interval)
