import threading
import time

from ingestion.scheduler import Job, start_scheduler


def test_scheduler_runs_job_repeatedly_until_stopped():
    counter = {"n": 0}
    lock = threading.Lock()

    def run_once():
        with lock:
            counter["n"] += 1

    stop_event = threading.Event()
    threads = start_scheduler([Job("dummy", run_once, interval_seconds=0)], stop_event)

    time.sleep(0.05)
    stop_event.set()
    for t in threads:
        t.join(timeout=1)

    assert counter["n"] > 1, "expected the job to loop more than once before stopping"
    assert not any(t.is_alive() for t in threads)


def test_scheduler_survives_job_exceptions():
    counter = {"n": 0}

    def flaky():
        counter["n"] += 1
        raise RuntimeError("simulated failure")

    stop_event = threading.Event()
    threads = start_scheduler([Job("flaky", flaky, interval_seconds=0)], stop_event)

    time.sleep(0.05)
    stop_event.set()
    for t in threads:
        t.join(timeout=1)

    assert counter["n"] > 1, "a raising job must not kill its own loop"


def test_scheduler_runs_multiple_jobs_independently():
    counters = {"a": 0, "b": 0}

    stop_event = threading.Event()
    threads = start_scheduler(
        [
            Job("a", lambda: counters.__setitem__("a", counters["a"] + 1), interval_seconds=0),
            Job("b", lambda: counters.__setitem__("b", counters["b"] + 1), interval_seconds=0),
        ],
        stop_event,
    )

    time.sleep(0.05)
    stop_event.set()
    for t in threads:
        t.join(timeout=1)

    assert counters["a"] > 1
    assert counters["b"] > 1
