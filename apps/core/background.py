"""
Background threads: the backup scheduler and the ping monitor.

They run inside the process started by `python manage.py serve` (or alone with `manage.py run_background`
when the web server is gunicorn/uwsgi). Backup job progress lives in the database, so several
processes can safely share it.
"""
import logging
import sys
import threading
import time

from django.conf import settings
from django.db import connections

logger = logging.getLogger("dbms")
_started = False


def _run_forever(name, func, interval, first_delay):
    def loop():
        time.sleep(first_delay)
        while not sys.is_finalizing():
            try:
                func()
            except Exception:
                # Interpreter shutdown can begin while daemon background threads are alive.
                # Avoid noisy shutdown tracebacks; log normal runtime failures as before.
                if not sys.is_finalizing():
                    logger.exception("%s error", name)
            finally:
                connections.close_all()          # each thread closes its own database connections
            if sys.is_finalizing():
                break
            time.sleep(interval)
    threading.Thread(target=loop, name=name, daemon=True).start()


def start_background():
    """Start the scheduler (checks every 30 s) and continuous full-inventory ping monitor. Safe twice."""
    global _started
    if _started:
        return
    _started = True
    # background.py is the composition root of the periodic work: it only starts other apps' services.
    from apps.backups.jobs import close_stale_jobs
    from apps.backups.services import prune_old_logs
    from apps.monitoring.services import ping_monitor_tick
    from apps.scheduling.services import scheduler_tick

    close_stale_jobs()
    _run_forever("scheduler", scheduler_tick, 30, first_delay=30)
    _run_forever("log-retention", prune_old_logs, 24 * 3600, first_delay=120)
    if settings.PING_SECONDS > 0:
        _run_forever("ping-monitor", ping_monitor_tick, max(15, settings.PING_SECONDS), first_delay=10)
