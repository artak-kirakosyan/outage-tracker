import logging
import threading
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from ingestion.scheduler import Job, start_scheduler

logger = logging.getLogger(__name__)


def _make_guarded_run(command_name: str, enabled_setting_name: str):
    """
    Wrap a fetch management command so the SCHEDULER (only) respects the
    provider's enabled/disabled switch. The job's thread keeps running on
    its normal schedule either way — when disabled, each tick just logs
    and skips the actual fetch, rather than not being scheduled at all.
    That way turning a provider back on only means flipping the env var
    and restarting, not re-architecting anything.
    """

    def run_once() -> None:
        if not getattr(settings, enabled_setting_name):
            logger.info("'%s' is disabled, skipping...", command_name, )
            return
        call_command(command_name)

    return run_once


class Command(BaseCommand):
    help = (
        "Run all Phase 0.5 fetchers forever, each on its own interval. "
        "See *_FETCH_ENABLED settings/env to disable a provider."
    )

    def handle(self, *args, **options):
        # (command name, enabled-flag setting name, interval setting)
        provider_configs = [
            ("fetch_ena", "ENA_FETCH_ENABLED", settings.ENA_FETCH_INTERVAL_MINUTES),
            ("fetch_veolia_web", "VEOLIA_WEB_FETCH_ENABLED", settings.VEOLIA_WEB_FETCH_INTERVAL_MINUTES),
            (
                "fetch_veolia_telegram",
                "VEOLIA_TELEGRAM_FETCH_ENABLED",
                settings.VEOLIA_TELEGRAM_FETCH_INTERVAL_MINUTES,
            ),
        ]

        jobs = [
            Job(name, _make_guarded_run(name, enabled_setting), interval_minutes * 60)
            for name, enabled_setting, interval_minutes in provider_configs
        ]

        for (name, enabled_setting, _), job in zip(provider_configs, jobs):
            disabled_note = "" if getattr(settings, enabled_setting) else " (disabled)"
            self.stdout.write(f"Scheduling {job.name} every {job.interval_seconds // 60} min{disabled_note}")

        stop_event = threading.Event()
        threads = start_scheduler(jobs, stop_event)

        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            self.stdout.write("Shutting down scheduler...")
            stop_event.set()
            for thread in threads:
                thread.join(timeout=5)
