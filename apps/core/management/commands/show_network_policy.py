"""Display the effective SSH destination allow-list without exposing credentials."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.netguard import _networks


class Command(BaseCommand):
    help = "Show which device management networks VAULT is allowed to SSH to."

    def handle(self, *args, **options):
        try:
            networks = _networks()
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write("Configured DBMS_ALLOWED_NETWORKS:")
        if networks:
            for network in networks:
                self.stdout.write(f"  - {network}")
            self.stdout.write("Policy: a device hostname must resolve entirely inside the listed networks.")
        else:
            self.stdout.write("  (empty)")
            self.stdout.write("Policy: no allow-list. Any address is accepted except loopback, link-local, "
                              "multicast and reserved addresses.")
        self.stdout.write(f"Offline reconnect retry: {settings.RECONNECT_RETRY_SECONDS} seconds")
