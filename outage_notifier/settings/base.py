"""
Base settings, shared by every environment.

Design intent (see docs/phase-0.5-plan.md): SQLite now, Postgres later,
purely via env vars / the DATABASES dict below — no code changes needed
to switch. Keep this file environment-agnostic; put anything
local-machine-specific in local.py.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-for-production")

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ingestion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "outage_notifier.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "outage_notifier.wsgi.application"
ASGI_APPLICATION = "outage_notifier.asgi.application"

# --- Database ---------------------------------------------------------
# Default: SQLite file under the repo root. To move to Postgres later,
# set DATABASE_URL-style env vars (or just replace this dict) — nothing
# else in the codebase talks to the DB except through the Django ORM,
# by design (see plan doc, "DB agnostic" decision).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

AUTH_PASSWORD_VALIDATORS = []  # not relevant yet; no public user auth in phase 0.5

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Yerevan"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Ingestion-specific settings --------------------------------------
# Where raw fetches are additionally mirrored as plain files on disk,
# mirroring the old repo's DUMP_DIRECTORY pattern. Purely for manual
# eyeballing while designing the Phase 1 parser; the DB row is the
# source of truth.
RAW_DUMP_DIRECTORY = Path(os.environ.get("RAW_DUMP_DIRECTORY", str(BASE_DIR / ".dumps")))

HTTP_FETCH_TIMEOUT_SECONDS = int(os.environ.get("HTTP_FETCH_TIMEOUT_SECONDS", "15"))
HTTP_FETCH_USER_AGENT = os.environ.get(
    "HTTP_FETCH_USER_AGENT",
    "Mozilla/5.0 (compatible; outage-notifier-bot/0.1; +local)",
)

VEOLIA_TELEGRAM_CHANNEL = os.environ.get("VEOLIA_TELEGRAM_CHANNEL", "VeoliaJur")

# Independent per-provider polling cadence for the v1 in-process scheduler
# (see ingestion/scheduler.py). Deliberately different defaults: the
# Telegram channel posts emergency outages as they happen, so it's
# polled more often than the two "planned outage" website sources.
ENA_FETCH_INTERVAL_MINUTES = int(os.environ.get("ENA_FETCH_INTERVAL_MINUTES", "60"))
VEOLIA_WEB_FETCH_INTERVAL_MINUTES = int(os.environ.get("VEOLIA_WEB_FETCH_INTERVAL_MINUTES", "60"))
VEOLIA_TELEGRAM_FETCH_INTERVAL_MINUTES = int(
    os.environ.get("VEOLIA_TELEGRAM_FETCH_INTERVAL_MINUTES", "15")
)

def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# Per-provider on/off switch for the scheduler (see run_scheduler.py for
# what "disabled" actually does).
ENA_FETCH_ENABLED = _env_bool("ENA_FETCH_ENABLED", True)
VEOLIA_WEB_FETCH_ENABLED = _env_bool("VEOLIA_WEB_FETCH_ENABLED", True)
VEOLIA_TELEGRAM_FETCH_ENABLED = _env_bool("VEOLIA_TELEGRAM_FETCH_ENABLED", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
