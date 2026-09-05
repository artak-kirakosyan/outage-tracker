import pytest

from outage_notifier.settings.base import _env_bool

TRUTHY = ["true", "True", "TRUE", "1", "yes", "Yes", "on", "ON"]
FALSY = ["false", "False", "0", "no", "off", "", "garbage", "  "]


@pytest.mark.parametrize("raw", TRUTHY)
def test_env_bool_recognizes_truthy_strings(monkeypatch, raw):
    monkeypatch.setenv("SOME_TEST_FLAG", raw)
    assert _env_bool("SOME_TEST_FLAG", default=False) is True


@pytest.mark.parametrize("raw", FALSY)
def test_env_bool_recognizes_falsy_strings(monkeypatch, raw):
    monkeypatch.setenv("SOME_TEST_FLAG", raw)
    assert _env_bool("SOME_TEST_FLAG", default=True) is False


def test_env_bool_falls_back_to_default_when_var_is_unset(monkeypatch):
    monkeypatch.delenv("SOME_TEST_FLAG", raising=False)
    assert _env_bool("SOME_TEST_FLAG", default=True) is True
    assert _env_bool("SOME_TEST_FLAG", default=False) is False
