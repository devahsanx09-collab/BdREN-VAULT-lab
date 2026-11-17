"""Prune old snapshots safely. Dry-run by default; pass --apply to delete files."""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'List or remove backup snapshots older than N days, preserving each device latest snapshot.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=180, help='Retention age in days (default: 180)')
        parser.add_argument('--apply', action='store_true', help='Actually delete eligible files; without this, dry-run only')

    def handle(self, *args, **options):
        days = options['days']
        if days < 1:
            self.stderr.write(self.style.ERROR('--days must be at least 1'))
            return
        root = Path(settings.BACKUP_DIR).resolve()
        if not root.is_dir():
            self.stdout.write('Backup directory does not exist; nothing to do.')
            return
        cutoff = timezone.now().timestamp() - timedelta(days=days).total_seconds()
        count = freed = 0
        for device_dir in (p for p in root.iterdir() if p.is_dir()):
            snapshots = sorted((p for p in device_dir.rglob('*.txt') if p.is_file()), key=lambda p: (p.stat().st_mtime, str(p)))
            for path in snapshots[:-1]:  # always preserve the latest snapshot for each device
                try:
                    resolved = path.resolve()
                    if root not in resolved.parents or path.stat().st_mtime >= cutoff:
                        continue
                    size = path.stat().st_size
                    count += 1
                    freed += size
                    self.stdout.write(f"{'DELETE' if options['apply'] else 'WOULD DELETE'} {path.relative_to(root)}")
                    if options['apply']:
                        path.unlink()
                        for sidecar in (path.with_suffix(path.suffix + '.sha256'), path.with_suffix('.sha256')):
                            if sidecar.is_file():
                                sidecar.unlink()
                except OSError as exc:
                    self.stderr.write(f'Could not process {path}: {exc}')
        mode = 'Deleted' if options['apply'] else 'Dry run: eligible'
        self.stdout.write(self.style.WARNING(f'{mode}: {count} snapshots, approximately {freed / (1024**2):.2f} MiB.'))
        if not options['apply']:
            self.stdout.write('No files were deleted. Re-run with --apply only after reviewing the list.')
