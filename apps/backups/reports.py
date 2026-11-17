"""Configuration change report: what changed on every device in the last 1, 3, 6 or 12 months.

Only CHANGED configurations are saved as files (unchanged runs write no file), so every saved version
inside the period is one configuration change. Each change is compared with the version before it -
for the first change in the period that is the last version saved BEFORE the period ("baseline").
Volatile lines (timestamps, "Building configuration ..." and similar) are ignored, exactly as when
a backup decides whether a configuration changed (services.normalize).
"""
import difflib
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from django.utils import timezone

from apps.devices import selectors as devices

from . import storage
from .services import normalize

PERIODS = {1: 30, 3: 91, 6: 182, 12: 365}       # months -> days
PREVIEW_LINES = 8                               # changed lines shown per change in the report
MAX_CHANGES = 200                               # per device, newest kept


def _when(path):
    """Snapshot time from its file name (device_YYYYMMDD_HHMMSS.txt), else the file time."""
    m = re.search(r"_(\d{8})_(\d{6})$", path.stem)
    tz = timezone.get_current_timezone()
    if m:
        try:
            return datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=tz)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=tz)


def _compare(old_text, new_text):
    """(lines added, lines removed, short preview of the changed lines)."""
    old_lines, new_lines = normalize(old_text).splitlines(), normalize(new_text).splitlines()
    added = removed = 0
    preview = []
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
        else:
            continue
        if len(preview) < PREVIEW_LINES and line[1:].strip():
            preview.append(line[0] + " " + line[1:].strip()[:160])
    return added, removed, preview


def month_range(from_month, to_month):
    """("2026-01", "2026-03") -> (1 Jan 2026 00:00, 31 Mar 2026 23:59:59) in local time; raises ValueError."""
    tz = timezone.get_current_timezone()
    start = datetime.strptime(from_month, "%Y-%m").replace(tzinfo=tz)
    last = datetime.strptime(to_month, "%Y-%m").replace(tzinfo=tz)
    nxt = last.replace(year=last.year + 1, month=1) if last.month == 12 else last.replace(month=last.month + 1)
    end = nxt - timedelta(seconds=1)
    if end < start:
        raise ValueError("The end month is before the start month")
    return start, end


# Saved backups never change once written, so a comparison is cached by (file, modification time).
# With 500-1000 devices the first report reads the files once; later reports reuse the results.
@lru_cache(maxsize=20000)
def _compare_files(old_path, old_mtime, new_path, new_mtime):
    added, removed, preview = _compare(Path(old_path).read_text(encoding="utf-8", errors="replace"),
                                       Path(new_path).read_text(encoding="utf-8", errors="replace"))
    return added, removed, tuple(preview)


@lru_cache(maxsize=20000)
def _line_count(path, mtime):
    return len(normalize(Path(path).read_text(encoding="utf-8", errors="replace")).splitlines())


def change_report(months=None, start=None, end=None):
    """Changes in the last `months` (1, 3, 6, 12), or between `start` and `end` (a chosen month range)."""
    now = timezone.localtime()
    if start is None:
        start = now - timedelta(days=PERIODS[months])
    end = min(end or now, now)
    root = storage.root()
    devices_by_key = {}
    for d in devices.devices_by_id():
        for key in (d.name, d.ip, d.ip.replace(".", "_")):
            if key:
                devices_by_key.setdefault(storage.safe_name(key).lower(), d)

    rows = []
    folders = [f for f in root.iterdir() if f.is_dir()] if root.is_dir() else []
    for folder in folders:
        files = storage.versions(folder)
        if not files:
            continue
        dated = [(f, t) for f in files for t in (_when(f),) if t <= end]       # versions saved after the range are ignored
        if not dated:
            continue
        before = [f for f, t in dated if t < start]
        inside = [(f, t) for f, t in dated if t >= start]
        prev = before[-1] if before else None
        changes = []
        for f, t in inside:
            entry = {"file": f.relative_to(folder).as_posix(), "time": t.strftime("%Y-%m-%d %H:%M:%S"),
                     "prev": prev.relative_to(folder).as_posix() if prev else ""}
            if prev is None:
                entry.update(first=True, added=_line_count(str(f), f.stat().st_mtime_ns), removed=0, preview=[])
            else:
                added, removed, preview = _compare_files(str(prev), prev.stat().st_mtime_ns, str(f), f.stat().st_mtime_ns)
                preview = list(preview)
                if not added and not removed:
                    # Saved only because a clock / "last change" line differed (older builds, e.g. IOS XR):
                    # not a real change, so it is left out and the next version compares with the same base.
                    continue
                entry.update(first=False, added=added, removed=removed, preview=preview)
            changes.append(entry)
            prev = f
        device = devices_by_key.get(folder.name.lower())
        real = [c for c in changes if not c["first"]]
        rows.append({
            "device": folder.name,
            "device_id": device.pk if device else None,
            "ip": device.ip if device else "",
            "type": device.device_type if device else "",
            "changes": len(real),
            "first_backup_in_period": any(c["first"] for c in changes),
            "added": sum(c["added"] for c in real),
            "removed": sum(c["removed"] for c in real),
            "last_change": changes[-1]["time"] if changes else "",
            "baseline": before[-1].relative_to(folder).as_posix() if before else "",
            "latest": dated[-1][0].relative_to(folder).as_posix(),        # newest version inside the range
            "timeline": list(reversed(changes))[:MAX_CHANGES],          # newest first
        })
    rows.sort(key=lambda r: (-r["changes"], r["last_change"] == "", r["device"].lower()))
    changed = [r for r in rows if r["changes"]]
    return {
        "months": months, "from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d"),
        "summary": {"devices": len(rows), "changed": len(changed), "unchanged": len(rows) - len(changed),
                    "changes": sum(r["changes"] for r in rows), "added": sum(r["added"] for r in rows),
                    "removed": sum(r["removed"] for r in rows)},
        "devices": rows,
    }
