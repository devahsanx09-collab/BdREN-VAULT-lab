#!/usr/bin/env bash
# =====================================================================================================
#  Build a SOURCE-HIDDEN distribution of VAULT (for giving the app to others to RUN without the code).
#
#  Every .py under apps/ and config/ (except __init__.py and migrations/) is compiled to a native
#  .so with Cython, then the .py sources are removed from the OUTPUT copy. What stays, because Django
#  needs it or it is visible anyway:
#      - templates/ (HTML), static/ (CSS, JS)     <- always readable in the browser
#      - */migrations/                            <- Django imports these as modules
#      - manage.py, __init__.py, .env.example
#
#  IMPORTANT - build where you will run:
#      A .so file is tied to the OS, CPU and Python version. Build on the SAME Ubuntu + Python as the
#      target server (or an identical machine). A build made here will not run on a different Python.
#
#  Usage (on the Linux build/server box):
#      sudo apt install -y build-essential python3-dev
#      python3 -m pip install cython
#      bash deploy/build_compiled.sh [OUTPUT_DIR]          # default: ../BdREN-VAULT-compiled
#
#  Then TEST before shipping (do not trust an untested compile):
#      cd OUTPUT_DIR
#      python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
#      .venv/bin/python manage.py check
#      # and run the full test suite
#
#  Ship OUTPUT_DIR the same way as the normal package; deploy/install.sh works on it unchanged.
# =====================================================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$(cd "$SRC/.." && pwd)/BdREN-VAULT-compiled}"
PY="${PYTHON:-python3}"

command -v gcc >/dev/null 2>&1 || { echo "Need a C compiler. Run: sudo apt install -y build-essential python3-dev"; exit 1; }
"$PY" -c "import sysconfig, os; p=sysconfig.get_path('include'); open(os.path.join(p,'Python.h')) if os.path.exists(os.path.join(p,'Python.h')) else (_ for _ in ()).throw(SystemExit(1))" 2>/dev/null \
  || { echo "Need the Python headers. Run: sudo apt install -y python3-dev"; exit 1; }
"$PY" -c "import Cython" 2>/dev/null || { echo "Need Cython. Run: $PY -m pip install cython"; exit 1; }

echo "Source : $SRC"
echo "Output : $OUT"
[ "$OUT" != "$SRC" ] || { echo "Choose an output directory different from the source."; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"
rsync -a --exclude='.venv/' --exclude='data/' --exclude='logs/' --exclude='staticfiles/' \
         --exclude='.env' --exclude='*.key' \
         --exclude='__pycache__/' --exclude='*.pyc' --exclude='.git/' --exclude='*.zip' \
         "$SRC/" "$OUT/"

cd "$OUT"
echo "Compiling Python modules to native .so (this can take a few minutes)..."
"$PY" <<'PY'
import glob
from setuptools import setup
from Cython.Build import cythonize

files = [f for f in glob.glob("apps/**/*.py", recursive=True) + glob.glob("config/**/*.py", recursive=True)
         if not f.endswith("__init__.py") and "/migrations/" not in f]
if not files:
    raise SystemExit("No .py files found to compile - is this the project root?")
setup(
    name="bdren-vault-compiled",
    ext_modules=cythonize(files, language_level=3, quiet=True,
                          compiler_directives={"language_level": 3}),
    script_args=["build_ext", "--inplace"],
)
print("Compiled %d modules." % len(files))
PY

echo "Removing the .py sources that were compiled (keeping __init__.py, migrations, manage.py)..."
find apps config -name '*.py' ! -name '__init__.py' ! -path '*/migrations/*' -delete
find apps config -name '*.c' -delete
find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

echo
echo "Done. Source-hidden build is in: $OUT"
echo "  - the Python logic is now .so binaries under apps/ and config/ (no readable .py)"
echo "  - templates, static files, migrations and manage.py are kept (unavoidable)"
echo
echo "TEST it before shipping:"
echo "  cd \"$OUT\" && $PY -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python manage.py check"
