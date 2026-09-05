import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "outage_notifier.settings.local")

application = get_wsgi_application()
