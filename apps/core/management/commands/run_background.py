"""Only the background jobs (for setups where gunicorn/uwsgi serves the web pages)."""
import time

from django.core.management.base import BaseCommand

from apps.core.background import start_background


class Command(BaseCommand):
    help = "Run the backup scheduler and ping monitor without a web server."

    def handle(self, *args, **opts):
        start_background()
        self.stdout.write("Background scheduler running. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
