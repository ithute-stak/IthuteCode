import tempfile
import unittest
from pathlib import Path
from threading import Event
from ithutecode.jobs import JobQueue
from ithutecode.executor import Executor, ServiceLoop

class ExecutorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = 100
        self.queue = JobQueue(Path(tmp.name)/"db", lambda: self.now)
        self.queue.enqueue("one","project",{"decision":{"project_id":"project","decision":"repair"},"job":{}})
        self.allowed = True
        self.calls = 0

    def handler(self, job, guard):
        guard()
        self.calls += 1
        return {"outcome":"ok"}

    def executor(self, handler=None):
        return Executor(self.queue,lambda job:self.allowed,{"repair":handler or self.handler},lease_seconds=10)

    def test_complete(self):
        self.assertEqual(self.executor().run_once(),"completed")
        self.assertEqual(self.queue.status("one")["status"],"completed")
        self.assertEqual(self.executor().run_once(),"idle")
        self.assertEqual(self.calls,1)

    def test_denied_before_execution(self):
        self.allowed = False
        self.assertEqual(self.executor().run_once(),"deferred")
        self.assertEqual(self.queue.status("one")["status"],"queued")
        self.assertEqual(self.calls,0)

    def test_revocation_during_execution(self):
        def handler(job,guard):
            self.allowed = False
            guard()
            self.fail("unexpected effect")
        self.assertEqual(self.executor(handler).run_once(),"uncertain")
        self.assertEqual(self.queue.status("one")["status"],"uncertain")

    def test_expiry_during_execution(self):
        def handler(job,guard):
            self.now += 11
            guard()
            self.fail("unexpected effect")
        self.assertEqual(self.executor(handler).run_once(),"uncertain")
        self.assertIsNone(self.queue.claim())

    def test_external_failure_is_uncertain(self):
        def handler(job,guard):
            raise OSError("unknown remote outcome")
        self.assertEqual(self.executor(handler).run_once(),"uncertain")
        self.assertEqual(self.executor().run_once(),"idle")

    def test_unsupported(self):
        self.assertEqual(Executor(self.queue,lambda job:True,{}).run_once(),"unsupported")

    def test_loop_order_and_stop(self):
        calls = []
        stop = Event()
        class Stage:
            def __init__(self,name): self.name=name
            def run_once(self):
                calls.append(self.name)
                if self.name=="dispatch": stop.set()
                return self.name
        loop=ServiceLoop([Stage("reconcile"),Stage("dispatch"),Stage("execute")])
        self.assertEqual(loop.tick(stop),["reconcile","dispatch"])
        self.assertEqual(calls,["reconcile","dispatch"])
        loop.run(stop)
        self.assertEqual(len(calls),2)
