"""Production-style server: `python manage.py serve` (waitress + background scheduler)."""
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.wsgi import get_wsgi_application

from apps.core.background import start_background


class Command(BaseCommand):
    help = "Run the web server (waitress) together with the scheduler and ping monitor."

    def add_arguments(self, parser):
        # Safe default: only this PC. Put a reverse proxy (Caddy/nginx, see deploy/) in front for other
        # machines, or set HOST=0.0.0.0 in .env for plain LAN access.
        parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
        parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
        parser.add_argument("--threads", type=int, default=8)
        parser.add_argument("--no-background", action="store_true",
                            help="do not start the scheduler / ping monitor in this process")

    def handle(self, *args, **opts):
        from waitress import serve
        if not opts["no_background"]:
            start_background()
        self.stdout.write(f"VAULT listening on http://{opts['host']}:{opts['port']} (waitress)")
        extra = {}
        if settings.BEHIND_PROXY:
            # Believe X-Forwarded-* headers ONLY when they come from the local reverse proxy, so the real
            # client address reaches the login lockout and the audit log, and nobody can fake it.
            extra = dict(trusted_proxy="127.0.0.1", trusted_proxy_count=1,
                         trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"},
                         clear_untrusted_proxy_headers=True)
        serve(get_wsgi_application(), host=opts["host"], port=opts["port"], threads=opts["threads"],
              max_request_body_size=3 * 1024 * 1024,
              ident="",                 # no "Server: waitress" header: do not tell visitors what runs here
              **extra)
