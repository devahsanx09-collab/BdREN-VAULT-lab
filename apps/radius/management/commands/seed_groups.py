from django.core.management.base import BaseCommand

from apps.radius.services import seed_groups


class Command(BaseCommand):
    help = "Create/refresh super-admin, read-write, read-only group attributes in radgroupreply"

    def handle(self, *args, **opts):
        seed_groups()
        self.stdout.write(self.style.SUCCESS("Groups seeded."))
