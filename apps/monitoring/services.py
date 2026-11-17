"""Monitoring - business layer: ICMP ping (one device or many), the ping API answer and the background monitor.

The ping itself is an integration with the operating system (the `ping` command); the inventory comes from
apps.devices.selectors.
"""
import platform
import sys
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.utils import timezone

from apps.devices import selectors as devices
from apps.devices.vendors import HOSTRX

from .models import PingHistory

LATEST_KEY = "ping-latest"  # last full-inventory ping result, written by the monitor
FAILS_KEY = "ping-fails"    # consecutive failed sweeps per device id (offline only after 2 in a row)
IS_WIN = platform.system() == "Windows"


def ping_host(ip):
    """Check one device with ICMP. Returns {'up': bool, 'ms': float | None}.

    ICMP is the pre-check for automatic backup: an offline result prevents an SSH
    attempt for this cycle. The monitor and reconnect queue keep checking later, so a
    temporarily powered-off device is not permanently skipped.
    """
    if not HOSTRX.match(ip):
        return {"up": False, "ms": None}
    from django.conf import settings
    timeout_ms = max(250, min(int(getattr(settings, "PING_TIMEOUT_MS", 2000)), 5000))
    attempts = max(1, min(int(getattr(settings, "PING_ATTEMPTS", 2)), 3))
    kwargs = {"creationflags": 0x08000000} if IS_WIN else {}  # suppress Windows console flash
    for attempt in range(attempts):
        cmd = (["ping", "-n", "1", "-w", str(timeout_ms), ip] if IS_WIN else
               ["ping", "-c", "1", "-W", str(max(1, (timeout_ms + 999) // 1000)), ip])
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=(timeout_ms / 1000) + 2, **kwargs)
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        except (OSError, subprocess.SubprocessError):
            output = ""
        # Windows may return exit code 0 for some unreachable responses; require a TTL.
        if "ttl=" in output.lower():
            match = re.search(r"time[=<]\s*([\d.]+)\s*ms", output, re.I)
            return {"up": True, "ms": float(match.group(1)) if match else None}
        if attempt + 1 < attempts:
            import time
            time.sleep(0.15)
    return {"up": False, "ms": None}


def ping_many(ips, recheck=True):
    """Ping a list of hosts concurrently with a bounded worker pool; preserve input order.

    recheck=True gives every host that failed the first round a second chance. A burst of lost
    ICMP replies (busy server, Wi-Fi/LAN hiccup) used to show up as a sudden drop of the
    "Devices online" graph to 10-50%. If more than 40% fail at once the problem is most likely on
    the monitoring side, so we wait a few seconds before the second round.
    """
    if not ips:
        return []
    import time
    from django.conf import settings
    # A 500-device inventory is checked in parallel, but never launches one process
    # per device. 64 workers keeps the worst-case offline scan bounded on an 8-core host.
    # Scale with the inventory: 1000 devices get 63 parallel pings (one sweep of 1000 mostly-offline hosts
    # then takes about 2 minutes instead of 7), small inventories keep the configured value.
    configured = int(getattr(settings, "PING_WORKERS", 20))
    workers = max(1, min(max(configured, -(-len(ips) // 16)), 64, len(ips)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dbms-ping") as pool:
        results = list(pool.map(ping_host, ips))
        if recheck:
            failed = [i for i, r in enumerate(results) if not r["up"]]
            if failed:
                if len(failed) > max(5, len(ips) * 0.4):
                    time.sleep(3)
                for i, again in zip(failed, pool.map(ping_host, [ips[i] for i in failed])):
                    if again["up"]:
                        results[i] = again
    return results


def ping_devices(wanted_ids=()):
    """{device id: {up, ms}} for the Ping column. No ids: the monitor's latest sweep when it exists
    (instead of pinging the whole inventory again on every page load)."""
    if not wanted_ids:
        from django.core.cache import cache
        latest = cache.get(LATEST_KEY)
        if latest:
            return latest
    pairs = devices.id_ip_pairs(wanted_ids)
    results = ping_many([ip for _, ip in pairs])
    return {str(i): r for (i, _), r in zip(pairs, results)}


def ping_monitor_tick():
    """Continuously monitor the full inventory at the configured interval (default 60s)."""
    # Prevent submitting ThreadPoolExecutor work while Python is shutting down.
    if sys.is_finalizing():
        return
    from django.conf import settings
    from django.core.cache import cache
    inventory = devices.id_ip_pairs()
    if not inventory:
        return
    raw = ping_many([ip for _, ip in inventory])
    interval = int(getattr(settings, "PING_SECONDS", 60) or 60)
    # Same rule as the Device Inventory page: a device that was online is reported offline only after
    # it failed TWO sweeps in a row. One lost burst of ICMP replies (busy uplink, rate-limited ICMP)
    # used to make the Dashboard show e.g. 72 / 82 online while the inventory still showed 82 / 82.
    previous = cache.get(LATEST_KEY) or {}
    fails = cache.get(FAILS_KEY) or {}
    results = []
    for (device_id, _), r in zip(inventory, raw):
        key = str(device_id)
        if r["up"]:
            fails[key] = 0
            results.append(r)
            continue
        fails[key] = fails.get(key, 0) + 1
        before = previous.get(key)
        results.append(before if before and before.get("up") and fails[key] < 2 else r)
    keep = max(180, interval * 3)
    cache.set(FAILS_KEY, {str(i): fails.get(str(i), 0) for i, _ in inventory}, keep * 10)
    # The browser reads this full result instead of pinging every device on each page load.
    cache.set(LATEST_KEY, {str(i): r for (i, _), r in zip(inventory, results)}, keep)
    times = [r["ms"] for r in results if r["up"] and r["ms"] is not None]
    PingHistory.objects.create(total=len(inventory), up=sum(1 for r in results if r["up"]),
                               avg_ms=round(sum(times) / len(times), 1) if times else None)
    PingHistory.objects.filter(ts__lt=timezone.now() - timedelta(days=7)).delete()
