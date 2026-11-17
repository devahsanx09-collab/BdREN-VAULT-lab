"""
Django settings for VAULT.

Every deployment choice comes from an environment variable (or a `.env` file in the project
folder) so the same code runs on a laptop and on a server. See `.env.example` for the full list.
"""
import os
import secrets
import sys
from pathlib import Path

from apps.core.keys import load_or_create_key

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------- tiny .env loader (no extra dependency) ----------
def _load_dotenv(path):
    """Load simple KEY=VALUE entries; tolerate BOM, export, quotes and inline comments.

    Existing non-empty process environment variables take precedence. An empty
    variable in the shell does not suppress a value supplied by the project .env.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        if not os.environ.get(key):
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")

# Backward compatibility: older installs used NETBACKUP_* variable names. They still work.
for _old in [k for k in os.environ if k.startswith("NETBACKUP_")]:
    os.environ.setdefault("DBMS_" + _old[len("NETBACKUP_"):], os.environ[_old])


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        sys.exit(f"Environment variable {name} must be a whole number")


def env_flag(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# ---------- data folders (database, backups, keys) ----------
DATA_DIR = Path(os.environ.get("DBMS_DATA", BASE_DIR / "data"))
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Fernet key that encrypts device passwords. Never overwrite it: old passwords would become unreadable.
FERNET_KEY_FILE = DATA_DIR / "secret.key"

# ---------- core Django ----------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or \
    load_or_create_key(DATA_DIR / "session.key", lambda: secrets.token_bytes(32)).hex()
DEBUG = env_flag("DJANGO_DEBUG")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")   # add the server IP / domain in .env
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
ENABLE_ADMIN_SITE = env_flag("DBMS_ENABLE_ADMIN")       # Django's /admin/ is OFF unless you ask for it
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # project apps (one folder per responsibility, see README)
    "apps.core",
    "apps.accounts",
    "apps.devices",
    "apps.backups",
    "apps.scheduling",
    "apps.monitoring",
    "apps.radius",          # RADIUS Admin: FreeRADIUS users, devices (NAS) and audit
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Compress pages, API answers (device lists, logs) and CSS / JS on the way out: nginx does not compress
    # proxied answers by default, so everything used to travel at full size.
    "django.middleware.gzip.GZipMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",       # serves /static/ without nginx
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# ---------- database ----------
# MySQL 8 / MariaDB 10.6+ only: every table (devices, jobs, logs, settings, users, sessions) lives there.
# Passwords are read from .env only, never written in the code.
DB_ENGINE = os.environ.get("DBMS_DB_ENGINE", "mysql").strip().lower()
if DB_ENGINE != "mysql":
    sys.exit('VAULT uses MySQL / MariaDB only. Set DBMS_DB_ENGINE=mysql and the DBMS_DB_* settings in .env.')

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DBMS_DB_NAME", "dbms"),
        "USER": os.environ.get("DBMS_DB_USER", "dbms"),
        "PASSWORD": os.environ.get("DBMS_DB_PASSWORD", ""),
        "HOST": os.environ.get("DBMS_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DBMS_DB_PORT", "3306"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
        },
    }
}
if not DATABASES["default"]["PASSWORD"]:
    sys.exit("DBMS_DB_PASSWORD is not set. Add it to the .env file.")

# ---------- RADIUS Admin: second database, shared with FreeRADIUS ----------
# The rad* and nas tables come from the FreeRADIUS schema.sql; apps/radius/router.py sends the
# RADIUS pages to this database and keeps every other table in "default".
DATABASES["radius"] = {
    "ENGINE": "django.db.backends.mysql",
    "NAME": os.environ.get("RADIUS_DB_NAME", "radius"),
    "USER": os.environ.get("RADIUS_DB_USER", "radius"),
    "PASSWORD": os.environ.get("RADIUS_DB_PASSWORD", ""),      # set it in .env; never in the code
    "HOST": os.environ.get("RADIUS_DB_HOST", "127.0.0.1"),
    "PORT": os.environ.get("RADIUS_DB_PORT", "3306"),
    "CONN_MAX_AGE": 60,
    "OPTIONS": {"charset": "utf8mb4"},
}
DATABASE_ROUTERS = ["apps.radius.router.RadiusRouter"]
# FreeRADIUS reads the nas table only at start, so it is restarted after a device is added or removed.
RADIUS_RELOAD_CMD = os.environ.get("RADIUS_RELOAD_CMD", "sudo -n /usr/bin/systemctl restart freeradius")
# 1 = FreeRADIUS looks new switches up in the nas table on their first request (deploy/radius/
# enable_dynamic_clients.sh), so adding a switch needs no FreeRADIUS restart (no "dead time" on switches)
RADIUS_DYNAMIC_CLIENTS = env_flag("RADIUS_DYNAMIC_CLIENTS")
# Keeps UDP 1812/1813 open in ufw only for the devices on NAS Clients, run after a device is added or
# removed. Set by deploy/radius/enable_firewall_sync.sh (sudo -n /usr/local/sbin/dbms-radius-firewall); empty = off
RADIUS_FIREWALL_CMD = os.environ.get("RADIUS_FIREWALL_CMD", "").strip()
# How RADIUS user passwords are stored: "cleartext" (default, works with PAP and CHAP) or "ssha2"
# (salted SHA-256, PAP only - device CLI logins use PAP). Applies to passwords set from now on.
RADIUS_PASSWORD_MODE = os.environ.get("RADIUS_PASSWORD_MODE", "cleartext").strip().lower()
if RADIUS_PASSWORD_MODE not in ("cleartext", "ssha2"):
    sys.exit('RADIUS_PASSWORD_MODE must be "cleartext" or "ssha2"')

# ---------- users and sessions ----------
AUTH_USER_MODEL = "accounts.User"
# Password rules (used by the Users page, the first-run setup and "change my password").
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
# Authentication lifetime: browser-session cookie + 15-minute idle timeout by default.
# The cookie disappears when the browser is fully closed; active requests refresh
# the server-side expiry, while an idle session expires after DBMS_SESSION_MINUTES.
SESSION_MINUTES = max(5, min(env_int("DBMS_SESSION_MINUTES", env_int("DBMS_SESSION_HOURS", 0) * 60 or 15), 24 * 60))
SESSION_COOKIE_AGE = SESSION_MINUTES * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_NAME = "dbms_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False                  # the page's JavaScript reads it and sends X-CSRFToken
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# ---------- HTTPS / reverse proxy ----------
SECURE_COOKIES = env_flag("DBMS_SECURE_COOKIES")      # set to 1 only when served over HTTPS
BEHIND_PROXY = env_flag("DBMS_BEHIND_PROXY")          # trust X-Forwarded-* from ONE reverse proxy
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_SSL_REDIRECT = env_flag("DBMS_FORCE_HTTPS")
# Deliberately NOT forced: HSTS for all subdomains / browser preload would also force HTTPS on every other
# service under the same domain, which this application cannot know about.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
if SECURE_COOKIES:
    SECURE_HSTS_SECONDS = 31536000
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# ---------- language, time ----------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"      # fixed Bangladesh time for scheduler, database timestamps and UI
USE_TZ = True

# ---------- static files ----------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(exist_ok=True)
WHITENOISE_USE_FINDERS = True                 # serve straight from static/ - collectstatic is optional
WHITENOISE_AUTOREFRESH = DEBUG
# Every CSS / JS address carries ?v=<number> (templates/base.html) that changes with each release, so a
# browser may keep a file for a year. The default (60 s) made every page change ask about all 17 files again.
WHITENOISE_MAX_AGE = 0 if DEBUG else 365 * 24 * 60 * 60
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# ---------- VAULT behaviour ----------
MAX_WORKERS = 50                                         # ceiling for parallel SSH sessions (Settings page: 1 to 50)
WORKERS = max(1, min(env_int("WORKERS", 5), MAX_WORKERS))  # low-load default; the Settings page value wins
JOB_PROGRESS_BATCH = max(1, min(env_int("DBMS_PROGRESS_BATCH", 5), 25))
KEEP_VERSIONS = env_int("DBMS_KEEP_VERSIONS", 0)      # newest N backups per device, 0 = keep all
SSH_TIMEOUT = env_int("DBMS_SSH_TIMEOUT", 30)         # seconds; SSH connect/auth/banner timeout
PING_SECONDS = max(0, env_int("DBMS_PING_SECONDS", 100)) # low-load full-inventory ICMP interval; 0 = off
PING_WORKERS = max(1, min(env_int("DBMS_PING_WORKERS", 20), 64))   # ping_many() scales up for big inventories
PING_TIMEOUT_MS = max(250, min(env_int("DBMS_PING_TIMEOUT_MS", 1000), 5000))
PING_ATTEMPTS = max(1, min(env_int("DBMS_PING_ATTEMPTS", 1), 3))
SLOW_DEVICES = env_flag("DBMS_SLOW_DEVICES")          # more patient CLI handling for old switches
# ---- patient backups (docs/BACKUP_RELIABILITY.md) ----
# Reading a configuration: keep waiting while the device sends data; give up only after it was SILENT for
# COMMAND_IDLE_SECONDS, or when one device took longer than the COMMAND_TIMEOUT ceiling.
COMMAND_IDLE_SECONDS = max(15, min(env_int("DBMS_COMMAND_IDLE_SECONDS", 180), 3600))
COMMAND_TIMEOUT = max(60, min(env_int("DBMS_COMMAND_TIMEOUT", 3600), 4 * 3600))
try:                                                  # seconds between two new SSH logins (0 = no pacing)
    LOGIN_SPACING = max(0.0, min(float(os.environ.get("DBMS_LOGIN_SPACING", "0.5")), 10.0))
except ValueError:
    LOGIN_SPACING = 0.5
RETRY_PASS = env_flag("DBMS_RETRY_PASS", True)        # second pass inside a job for temporary failures
RETRY_COOLDOWN = max(0, min(env_int("DBMS_RETRY_COOLDOWN", 60), 3600))
RETRY_PASS_WORKERS = max(1, min(env_int("DBMS_RETRY_PASS_WORKERS", 3), 10))
RETRY_MAX_DAYS = max(1, min(env_int("DBMS_RETRY_MAX_DAYS", 7), 90))   # how long an offline device is waited for

# ---------- security switches (all default to the safe choice) ----------
# First administrator can only be created from the server PC itself (or with `createsuperuser`).
SETUP_FROM_ANYWHERE = env_flag("DBMS_SETUP_FROM_ANYWHERE")
# 1 (default) = an administrator may reveal a saved DEVICE password in the device form. 0 = never sent to a browser.
REVEAL_SAVED_PASSWORDS = env_flag("DBMS_REVEAL_PASSWORDS", True)
# Optional allow-list of management networks (comma-separated, e.g. 10.0.0.0/8,103.28.121.0/24).
# When set, SSH and ping go only to addresses inside it. Unset = any ordinary address (see apps/core/netguard.py).
ALLOWED_DEVICE_NETWORKS = env_list("DBMS_ALLOWED_NETWORKS")
# Recheck offline scheduled devices every 60 seconds by default (minimum 60 seconds).
RECONNECT_RETRY_SECONDS = max(60, min(env_int("DBMS_RECONNECT_RETRY_SECONDS", 60), 86400))
# 1 = remember each device's SSH host key on first contact and refuse a changed key (detects MITM).
SSH_HOSTKEY_CHECK = env_flag("DBMS_SSH_HOSTKEY_CHECK", True)
SSH_KNOWN_HOSTS = DATA_DIR / "known_hosts"

# ---------- logging ----------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO").upper()},
}

# Optional SMTP settings for backup failure notifications; unset means Django defaults.
EMAIL_HOST = os.environ.get("DBMS_EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("DBMS_EMAIL_PORT", 25)
EMAIL_HOST_USER = os.environ.get("DBMS_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DBMS_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("DBMS_EMAIL_USE_TLS", "0") == "1"
EMAIL_USE_SSL = os.environ.get("DBMS_EMAIL_USE_SSL", "0") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DBMS_EMAIL_FROM", EMAIL_HOST_USER or "dbms@localhost")
