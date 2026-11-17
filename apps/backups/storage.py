"""Safe filesystem storage for dated, year/date configuration snapshots.

Layout: data/backups/<device>/<YYYY>/<Mon>/<DD>/<device>_<timestamp>.txt
Each run also updates run.json in its day folder. Unchanged runs write metadata only,
never a duplicate configuration file.
"""
from django.core.cache import cache
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.core.api import ApiError
from apps.core.utils import DT_FORMAT


def root():
    return Path(settings.BACKUP_DIR)


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .") or "device"


def read_text(path):
    return path.read_text(encoding="utf-8", errors="replace")


def versions(folder):
    """Configuration snapshots under a device or date folder, oldest first.

    Prefer the timestamp embedded in current filenames so copying/restoring a backup
    does not accidentally make an old snapshot appear newer just because its mtime changed.
    Legacy filenames fall back to filesystem mtime.
    """
    if not folder.exists():
        return []

    def order(path):
        match = re.search(r"_(\d{8})_(\d{6})$", path.stem)
        if match:
            try:
                stamp = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").timestamp()
                return (stamp, str(path))
            except ValueError:
                pass
        return (path.stat().st_mtime, str(path))

    return sorted(folder.rglob("*.txt"), key=order)


def latest_file(folder):
    files = versions(folder)
    return files[-1] if files else None


def device_folder(name, create=False):
    folder = root() / safe_name(name)
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def day_folder(name, when=None):
    when = when or timezone.localtime()
    folder = device_folder(name, create=True) / f"{when:%Y}" / when.strftime("%b") / f"{when:%d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_run_metadata(folder, *, status, backup_at, last_change_at="", last_change_file="", message=""):
    _invalidate()
    payload = {
        "status": status,
        "backup_date": backup_at.strftime(DT_FORMAT),
        "last_change_date": last_change_at,
        "last_change_file": last_change_file,
        "message": message,
    }
    _write_json_atomic(folder / "run.json", payload)
    return payload


def _write_json_atomic(path, payload):
    """Write via a temp file + rename so a reader (or a crash) never sees a half-written run.json."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class StagedBackup:
    """A new snapshot written to a hidden temporary file, not yet visible as a backup.

    All-or-nothing saving (services.backup_device):
      1. stage_backup()    - the whole configuration is written and flushed to disk under a temporary name
                             (".part"; versions() only lists *.txt, so nobody can see or download it yet)
      2. publish_staged()  - one atomic rename, done INSIDE the database transaction that records the
                             backup, so the file and the database row appear together or not at all
      3. finalize_backup() - checksum, run.json and pruning, only after both are committed
    discard_staged() removes every trace when anything before the commit fails.
    """
    name: str
    when: datetime
    tmp: Path
    final: Path
    rel: str
    published: bool = False


def stage_backup(name, text, when=None):
    when = when or timezone.localtime()
    folder = day_folder(name, when)
    final = folder / f"{safe_name(name)}_{when:%Y%m%d_%H%M%S}.txt"
    fd, tmp = tempfile.mkstemp(prefix="." + final.name + ".", suffix=".part", dir=str(folder))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        _remove_empty_parents(folder, name)
        raise
    return StagedBackup(name, when, Path(tmp), final, final.relative_to(device_folder(name)).as_posix())


def publish_staged(staged):
    """Make the staged snapshot visible under its final name (atomic rename on the same disk)."""
    os.replace(staged.tmp, staged.final)
    staged.published = True
    _invalidate()


def discard_staged(staged):
    """Undo a staged (or just published) snapshot: the backup did not complete, so nothing may remain."""
    for path in (staged.tmp, staged.final if staged.published else None):
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    _remove_empty_parents(staged.final.parent, staged.name)
    _invalidate()


def _remove_empty_parents(folder, name):
    """Delete date folders left empty by a discarded snapshot (never the device folder itself)."""
    stop = device_folder(name)
    for parent in [folder, *folder.parents]:
        if parent == stop or parent == root():
            break
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
            else:
                break
        except OSError:
            break


def finalize_backup(staged):
    """Checksum, day metadata and pruning for a snapshot that is already committed."""
    path = staged.final
    # SHA-256 sidecar for later integrity checks (hidden from the UI: versions() only lists *.txt).
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _write_text_atomic(path.with_suffix(path.suffix + ".sha256"), f"{digest}  {path.name}\n")
    write_run_metadata(path.parent, status="SUCCESS", backup_at=staged.when,
                       last_change_at=staged.when.strftime(DT_FORMAT), last_change_file=staged.rel,
                       message="Configuration changed; a new snapshot was saved.")
    _prune(staged.name)


def _write_text_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_backup(name, text, when=None):
    """Save a changed configuration in the date folder in one step (no database involved); return its relative path."""
    staged = stage_backup(name, text, when)
    try:
        publish_staged(staged)
    except BaseException:
        discard_staged(staged)
        raise
    finalize_backup(staged)
    return staged.rel


def _prune(name):
    keep = settings.KEEP_VERSIONS
    if keep > 0:
        for old in versions(device_folder(name))[:-keep]:
            old.unlink(missing_ok=True)
            old.with_suffix(old.suffix + ".sha256").unlink(missing_ok=True)
            for parent in old.parents:
                if parent == device_folder(name): break
                try:
                    if parent.is_dir() and not any(parent.iterdir()): parent.rmdir()
                except OSError:
                    break


def record_unchanged(name, when=None, last_file=None, last_change_at=""):
    _invalidate()
    """Record that a scheduled/manual check ran but config was unchanged; do not duplicate config."""
    when = when or timezone.localtime()
    folder = day_folder(name, when)
    # If a NEW snapshot was already saved earlier today, keep that SUCCESS record. Overwriting it with
    # "UNCHANGED" made the day look empty ("no data") in the Backups tree although the file exists.
    meta_file = folder / "run.json"
    if meta_file.is_file() and any(folder.glob("*.txt")):
        try:
            existing = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if isinstance(existing, dict) and existing.get("status") == "SUCCESS":
            existing["last_check_date"] = when.strftime(DT_FORMAT)
            _write_json_atomic(meta_file, existing)
            return existing
    rel = last_file.relative_to(device_folder(name)).as_posix() if last_file else ""
    if not last_change_at and last_file:
        mtime = datetime.fromtimestamp(last_file.stat().st_mtime, tz=timezone.get_current_timezone())
        last_change_at = mtime.strftime(DT_FORMAT)
    return write_run_metadata(folder, status="UNCHANGED", backup_at=when,
                              last_change_at=last_change_at, last_change_file=rel,
                              message="No configuration change. Previous saved configuration is retained.")


def file_info(path, device_root=None):
    st = path.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.get_current_timezone())
    filename = path.relative_to(device_root).as_posix() if device_root else path.name
    return {"file": filename, "name": path.name, "size": st.st_size, "time": mtime.strftime(DT_FORMAT)}


SUMMARY_KEY = "backup-summaries"
SUMMARY_TTL = 30  # seconds; every write below clears it, so the page is never stale for long


def summaries():
    """Backup folder summaries, cached briefly so a page load does not walk the whole backup tree."""
    data = cache.get(SUMMARY_KEY)
    if data is None:
        data = _scan_summaries()
        cache.set(SUMMARY_KEY, data, SUMMARY_TTL)
    return data


def _invalidate():
    cache.delete(SUMMARY_KEY)


def _scan_summaries():
    """One summary per device: saved configuration count, latest snapshot and last check."""
    out = []
    if not root().is_dir():
        return out
    for folder in root().iterdir():
        if not folder.is_dir():
            continue
        files = versions(folder)
        if not files:
            continue
        latest = files[-1]
        out.append({"name": folder.name, "count": len(files), "latest": file_info(latest, folder),
                    "previous": files[-2].relative_to(folder).as_posix() if len(files) > 1 else ""})
    return sorted(out, key=lambda d: d["latest"]["time"], reverse=True)


def folder_of(name):
    base = root().resolve()
    folder = (root() / name).resolve()
    if folder.parent != base or not folder.is_dir():
        raise ApiError(404, "Not found")
    return folder


def folders_of(names):
    base, out = root().resolve(), []
    for name in names:
        if isinstance(name, str):
            folder = (root() / name).resolve()
            if folder.parent == base and folder.is_dir():
                out.append(folder)
    return out


def resolve(device, filename):
    folder = folder_of(device)
    path = (folder / filename).resolve()
    if folder.resolve() not in path.parents or not path.is_file() or path.suffix.lower() != ".txt":
        raise ApiError(404, "Not found")
    return path


def tree_for_device(folder):
    """Return a chronological Year > abbreviated Month > Day tree.

    Supports the current YYYY/Mon/DD layout plus older YYYY/YYYY-MM-DD and
    YYYY/MM/DD layouts without moving or renaming existing backup files.
    """
    years = []
    if not folder.exists():
        return {"device": folder.name, "years": []}

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_order = {name: i for i, name in enumerate(month_names, 1)}
    for yp in sorted((p for p in folder.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 4), reverse=True):
        month_map = {}
        for child in yp.iterdir():
            if not child.is_dir():
                continue
            # New layout: <year>/<Mon>/<DD>
            if child.name in month_order:
                mnum = month_order[child.name]
                for dp in child.iterdir():
                    if dp.is_dir() and dp.name.isdigit() and 1 <= int(dp.name) <= 31:
                        month_map.setdefault(mnum, []).append((int(dp.name), dp))
            # Legacy layout: <year>/<MM>/<DD>
            elif child.name.isdigit() and len(child.name) <= 2 and 1 <= int(child.name) <= 12:
                mnum = int(child.name)
                for dp in child.iterdir():
                    if dp.is_dir() and dp.name.isdigit() and 1 <= int(dp.name) <= 31:
                        month_map.setdefault(mnum, []).append((int(dp.name), dp))
            # Older layout: <year>/<YYYY-MM-DD>
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
                try:
                    dt = datetime.strptime(child.name, "%Y-%m-%d")
                    month_map.setdefault(dt.month, []).append((dt.day, child))
                except ValueError:
                    continue

        months = []
        for mnum in sorted(month_map, reverse=True):
            days = []
            seen = set()
            for day_num, dp in sorted(month_map[mnum], key=lambda x: x[0], reverse=True):
                # Avoid duplicate representation if a migration left equivalent folders.
                identity = str(dp.resolve())
                if identity in seen:
                    continue
                seen.add(identity)
                meta = {}
                mf = dp / "run.json"
                if mf.is_file():
                    try:
                        meta = json.loads(mf.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        meta = {}
                files = [file_info(f, folder) for f in sorted(dp.glob("*.txt"), key=lambda p: (p.stat().st_mtime, p.name), reverse=True)]
                if meta or files:
                    days.append({"day": f"{day_num:02d}", "date": f"{yp.name}-{mnum:02d}-{day_num:02d}",
                                 "metadata": meta, "files": files})
            if days:
                months.append({"month": month_names[mnum-1], "month_number": mnum, "days": days})
        if months:
            years.append({"year": yp.name, "months": months})
    return {"device": folder.name, "years": years}


def delete_file(path):
    _invalidate()
    device_root = path
    while device_root.parent != root().resolve() and device_root.parent != device_root:
        device_root = device_root.parent
    path.unlink()
    # Remove the matching checksum when a configuration snapshot is deleted.
    path.with_suffix(path.suffix + ".sha256").unlink(missing_ok=True)
    for parent in path.parents:
        if parent == device_root or parent == root():
            break
        try:
            if parent.is_dir() and not any(parent.iterdir()): parent.rmdir()
        except OSError:
            break


def delete_folders(folders):
    _invalidate()
    count = 0
    for folder in folders:
        count += len(list(folder.rglob("*.txt")))
        shutil.rmtree(folder)
    return count


def _archive_snapshot_name(folder, path):
    """Stable, portable archive name: HOSTNAME_YYYYMMDD.txt."""
    # Current snapshots include YYYYMMDD_HHMMSS in the basename. Older backups may not,
    # so fall back to the file's modification date in the configured local timezone.
    match = re.search(r"_(\d{8})(?:_\d{6})?$", path.stem)
    if match:
        date_part = match.group(1)
    else:
        from datetime import timezone as dt_timezone
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=dt_timezone.utc).astimezone(timezone.get_current_timezone())
        date_part = stamp.strftime("%Y%m%d")
    return f"{safe_name(folder.name)}_{date_part}.txt"


def zip_of(folders, every_version=False):
    """Create an in-memory ZIP. Latest mode contains one dated TXT per device."""
    buf, count = io.BytesIO(), 0
    used_names = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in folders:
            files = versions(folder)
            for f in (files if every_version else files[-1:]):
                if every_version:
                    arc = f"{safe_name(folder.name)}/{f.relative_to(folder).as_posix()}"
                else:
                    arc = _archive_snapshot_name(folder, f)
                    # Avoid silently replacing an entry if legacy folders contain colliding names.
                    if arc in used_names:
                        stem, suffix = arc[:-4], arc[-4:]
                        index = 2
                        while f"{stem}_{index}{suffix}" in used_names:
                            index += 1
                        arc = f"{stem}_{index}{suffix}"
                    used_names.add(arc)
                z.write(f, arc)
                count += 1
    buf.seek(0)
    return buf, count
