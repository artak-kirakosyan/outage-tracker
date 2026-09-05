from unittest.mock import patch

from ingestion.management.commands.run_scheduler import _make_guarded_run


@patch("ingestion.management.commands.run_scheduler.call_command")
def test_guarded_run_calls_command_when_enabled(mock_call_command, settings):
    settings.ENA_FETCH_ENABLED = True

    run_once = _make_guarded_run("fetch_ena", "ENA_FETCH_ENABLED")
    run_once()

    mock_call_command.assert_called_once_with("fetch_ena")


@patch("ingestion.management.commands.run_scheduler.call_command")
def test_guarded_run_skips_command_when_disabled(mock_call_command, settings):
    settings.VEOLIA_WEB_FETCH_ENABLED = False

    run_once = _make_guarded_run("fetch_veolia_web", "VEOLIA_WEB_FETCH_ENABLED")
    run_once()

    mock_call_command.assert_not_called()


@patch("ingestion.management.commands.run_scheduler.call_command")
def test_guarded_run_defaults_to_enabled(mock_call_command, settings):
    settings.VEOLIA_TELEGRAM_FETCH_ENABLED = True

    run_once = _make_guarded_run("fetch_veolia_telegram", "VEOLIA_TELEGRAM_FETCH_ENABLED")
    run_once()

    mock_call_command.assert_called_once_with("fetch_veolia_telegram")
