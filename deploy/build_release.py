"""Build the release zip of this project:  python deploy/build_release.py [output.zip]

Packs the project folder as vault/... with forward-slash paths (Linux unzip friendly), leaving out only what
is created at run time or must never ship:
  - top-level runtime folders: data/, logs/ (an empty logs/README.md is kept), staticfiles/, .venv/, venv/
  - anywhere: __pycache__/, *.pyc, tests.py, .env
Folders with the same name deeper in the project (templates/logs/, for example) ARE included.
Then checks that every template, static file, Python module and deploy script of the project is in the zip.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP_LEVEL_SKIP = {"data", "logs", "staticfiles", ".venv", "venv", ".git", ".idea", ".vscode"}
ANYWHERE_SKIP_DIRS = {"__pycache__"}
SKIP_FILES = {".env", "tests.py"}
SKIP_SUFFIXES = {".pyc"}


def wanted(rel):
    parts = rel.parts
    if parts[0] in TOP_LEVEL_SKIP and len(parts) > 1:
        return rel.as_posix() == "logs/README.md"
    if any(p in ANYWHERE_SKIP_DIRS for p in parts):
        return False
    return rel.name not in SKIP_FILES and rel.suffix not in SKIP_SUFFIXES


def build(out):
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and wanted(p.relative_to(ROOT)))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            # Fixed Linux permissions inside the zip: owner may write, everyone else may only read
            # (scripts may also be run). A zip built on Windows otherwise unpacks every program file as
            # rw-rw-rw-, so any other account on the server could change the application's code.
            info = zipfile.ZipInfo.from_file(p, "vault/" + p.relative_to(ROOT).as_posix())
            info.create_system = 3                                   # Unix: unzip applies the mode below
            info.external_attr = (0o100755 if p.suffix == ".sh" else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    names = set(zipfile.ZipFile(out).namelist())
    loose = [i.filename for i in zipfile.ZipFile(out).infolist() if (i.external_attr >> 16) & 0o022]
    if loose:
        sys.exit(f"Release check FAILED. Writable by other accounts: {loose[:10]}")
    # every source file that matters must be inside
    must = [p for p in ROOT.rglob("*") if p.is_file() and p.relative_to(ROOT).parts[0] in
            ("apps", "config", "templates", "static", "deploy", "docs") and wanted(p.relative_to(ROOT))]
    missing = [p.relative_to(ROOT).as_posix() for p in must if "vault/" + p.relative_to(ROOT).as_posix() not in names]
    leaked = [n for n in names if n.endswith((".env", ".pyc", "/tests.py")) or "/data/" in n]
    if missing or leaked:
        sys.exit(f"Release check FAILED. Missing: {missing[:10]} Not allowed: {leaked[:10]}")
    print(f"{out}: {len(names)} files, {Path(out).stat().st_size:,} bytes - every source file included")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else str(ROOT.parent / "BdREN-VAULT.zip"))
