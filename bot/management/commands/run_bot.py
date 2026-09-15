"""Runs the Telegram bot as a long-running polling process. Separate
from run_scheduler (see docker-compose.yml's bot service) so a bot
restart doesn't interrupt fetching."""
from django.conf import settings
from django.core.management.base import BaseCommand
from telegram.ext import Application

from bot.handlers import register_handlers


class Command(BaseCommand):
    help = "Run the Telegram bot (polling)."

    def handle(self, *args, **options):
        application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        register_handlers(application)
        application.run_polling()
