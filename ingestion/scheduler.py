"""
Minimal v1 scheduler: one daemon thread per provider, each looping on its
own interval. No Celery/APScheduler dependency — per the plan doc, "a
simple cron-in-container or a sleep loop is fine for v1". This is the
sleep-loop option, kept in-process so one `docker compose up` gives us a
single long-running scheduler service.

Revisit if/when Phase 1 needs retries-with-backoff, job overlap
protection, or distributed scheduling — none of that is needed yet.
"""
import logging
import threading
from typing import Callable, NamedTuple

logger = logging.getLogger(__name__)


class Job(NamedTuple):
    name: str
    run_once: Callable[[], None]
    interval_seconds: int


def _run_loop(job: Job, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            job.run_once()
        except Exception:  # noqa: BLE001 - a bad run must not kill the thread
            logger.exception("Unhandled error running scheduled job '%s'", job.name)
        stop_event.wait(job.interval_seconds)


def start_scheduler(jobs: list[Job], stop_event: threading.Event) -> list[threading.Thread]:
    """Start one daemon thread per job; each runs immediately, then waits
    `interval_seconds` between runs, until `stop_event` is set."""
    threads = []
    for job in jobs:
        thread = threading.Thread(
            target=_run_loop, args=(job, stop_event), daemon=True, name=job.name
        )
        thread.start()
        threads.append(thread)
    return threads
