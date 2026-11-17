"""The architecture rules of this project, checked automatically.

Every app (apps/<name>/) is built in layers; a module may only depend on layers below it:

    HTTP          views.py, urls.py           read the request, call selectors / services, answer
    business      services.py                 rules and every change (writes, transactions)
    read          selectors.py                every database read; never changes data
    integration   engine.py, storage.py,      the outside world: SSH, files on disk, background jobs,
                  jobs.py, reports.py, ...    the `ping` command, the FreeRADIUS database
    data          models.py                   tables only

Between apps, only the public modules of another app may be used (PUBLIC below); apps/core is the shared
kernel that every app may use. Maintenance commands (management/commands/) may use the
models of any app directly, like database migrations do. Run:  python manage.py check_architecture
"""
import ast
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

# modules of another app that may be imported (its public face)
PUBLIC = {"selectors", "services", "audit", "vendors", "jobs", "engine", "pages", "api", "utils", "crypto",
          "netguard", "keys", "alerts", "background", "router"}
HTTP = {"views", "urls"}
FORBIDDEN_IMPORTS = {
    # layer       : modules of the SAME app it must not import
    "models": {"views", "urls", "services", "selectors"},
    "selectors": {"views", "urls", "services"},
    "services": {"views", "urls"},
}


@dataclass
class Violation:
    path: str
    line: int
    rule: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.rule}"


def _imports(tree):
    """(line, "apps.x.y" or ".y", imported names) for every import in a module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            yield node.lineno, base, [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name, []


def _target(app, base, names):
    """Which (app, module) an import points to, for imports inside apps/; else None."""
    if base.startswith("."):
        mod = base.lstrip(".")
        if base.startswith("..") or not mod:          # "from . import services, selectors"
            return [(app, n) for n in names] if not mod else None
        return [(app, mod.split(".")[0])]
    parts = base.split(".")
    if parts[0] != "apps" or len(parts) < 2:
        return None
    if len(parts) == 2:                               # "from apps.devices import selectors"
        return [(parts[1], n) for n in names]
    return [(parts[1], parts[2])]


def check(root=None):
    """Return every Violation found under apps/ (empty list = the architecture is respected)."""
    root = Path(root or settings.BASE_DIR) / "apps"
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        parts = path.relative_to(root).parts
        if len(parts) < 2 or "migrations" in parts or parts[-1] == "tests.py":
            continue
        app, layer = parts[0], path.stem if len(parts) == 2 else parts[1]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        source = path.read_text(encoding="utf-8").splitlines()
        if layer in HTTP:
            for i, text in enumerate(source, 1):
                code = text.split("#", 1)[0]
                if ".objects." in code or "transaction.atomic" in code or "connection.cursor" in code:
                    found.append(Violation(rel, i, "HTTP layer must not query the database: use a selector or service"))
        for line, base, names in _imports(tree):
            for target_app, module in _target(app, base, names) or []:
                if layer in HTTP and module == "models":
                    found.append(Violation(rel, line, f"HTTP layer must not import models ({target_app}.models)"))
                if target_app == app and module in FORBIDDEN_IMPORTS.get(layer, ()):
                    found.append(Violation(rel, line, f"{layer} must not import {module} (layers point downwards only)"))
                if target_app not in (app, "core") and module not in PUBLIC and module != "models":
                    found.append(Violation(rel, line, f"use the public modules of {target_app}, not {target_app}.{module}"))
                if target_app not in (app, "core") and module == "models" and layer not in ("models", "admin", "management"):
                    found.append(Violation(rel, line, f"read {target_app} data through {target_app}.selectors, "
                                                      f"not {target_app}.models"))
    return found
