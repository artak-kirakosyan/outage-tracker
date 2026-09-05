import tempfile
from pathlib import Path

from .base import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Never let tests write into the real .dumps/ directory.
RAW_DUMP_DIRECTORY = Path(tempfile.mkdtemp(prefix="outage-notifier-test-dumps-"))
