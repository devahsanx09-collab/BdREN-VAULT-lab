"""python manage.py check_architecture  - verify the layer rules of apps/core/architecture.py."""
from django.core.management.base import BaseCommand, CommandError

from apps.core.architecture import check


class Command(BaseCommand):
    help = "Check that every app follows the layered architecture (HTTP -> services / selectors -> models)."

    def handle(self, *args, **options):
        problems = check()
        if problems:
            for p in problems:
                self.stderr.write(str(p))
            raise CommandError(f"{len(problems)} architecture rule(s) broken. See apps/core/architecture.py.")
        self.stdout.write(self.style.SUCCESS("Architecture OK: every app follows the layer rules."))
