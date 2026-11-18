#!/usr/bin/env bash
# Disaster-recovery backup: dumps the "dbms" and "radius" MySQL databases and copies the encryption /
# session keys into one timestamped set of files, so the whole system can be rebuilt if this server, its
# disk or its database is ever lost.
#
# This only WRITES to a local directory (default /var/backups/vault-dr). That copy is on the same disk as
# everything else, so it does NOT protect against losing this server. Copy that directory to another
# machine or off-site storage on your own (rsync/rclone/scp, or your existing backup system) - this script
# only prepares what to copy, and prunes old copies so the local directory does not grow forever.
#
# What it saves:
#   - mysqldump of the "dbms" database (devices, jobs, logs, settings, users, audit trail)
#   - mysqldump of the "radius" database (RADIUS/AAA users, NAS clients), if RADIUS_DB_PASSWORD is set
#   - secret.key and session.key - WITHOUT secret.key every saved device password becomes permanently
#     unreadable (it cannot be "reset"; devices would need their passwords re-entered one by one)
#   - the SSH known_hosts / per-device host-key files, so a restored server does not re-accept every
#     device's host key as if it were seeing it for the first time
# It does NOT copy the saved device configuration backups themselves (data/backups/, which can be large) -
# back those up with your normal file backup/snapshot, or add --with-configs to include them here too.
#
# Usage:  sudo bash /opt/vault/deploy/backup_vault.sh [destination-dir] [--with-configs]
#         Reads DBMS_DB_* / RADIUS_DB_* / DBMS_DATA from /opt/vault/.env (ENV_FILE=... to use another file).
#         Keeps the newest DR_KEEP_DAYS (default 14) days of archives in the destination directory.
#
# Run it daily from root's crontab for an automatic, unattended backup, for example:
#   0 3 * * * bash /opt/vault/deploy/backup_vault.sh >> /var/log/dbms-dr-backup.log 2>&1
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vault}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
KEEP_DAYS="${DR_KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WITH_CONFIGS=0
DEST=""
for a in "$@"; do
  case "$a" in
    --with-configs) WITH_CONFIGS=1 ;;
    *) DEST="$a" ;;
  esac
done
DEST="${DEST:-/var/backups/vault-dr}"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m    %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo:  sudo bash $0"
[ -r "$ENV_FILE" ] || die "Cannot read $ENV_FILE (set ENV_FILE=/path/to/.env)"
command -v mysqldump >/dev/null || die "mysqldump is not installed"

env_get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+|[[:space:]]+$//g' -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }

DBMS_DB_NAME="$(env_get DBMS_DB_NAME)"; DBMS_DB_NAME="${DBMS_DB_NAME:-dbms}"
DBMS_DB_USER="$(env_get DBMS_DB_USER)"; DBMS_DB_USER="${DBMS_DB_USER:-dbms}"
DBMS_DB_PASS="$(env_get DBMS_DB_PASSWORD)"
DBMS_DB_HOST="$(env_get DBMS_DB_HOST)"; DBMS_DB_HOST="${DBMS_DB_HOST:-127.0.0.1}"
DBMS_DB_PORT="$(env_get DBMS_DB_PORT)"; DBMS_DB_PORT="${DBMS_DB_PORT:-3306}"
[ -n "$DBMS_DB_PASS" ] || die "DBMS_DB_PASSWORD is empty in $ENV_FILE"

RAD_DB_NAME="$(env_get RADIUS_DB_NAME)"; RAD_DB_NAME="${RAD_DB_NAME:-radius}"
RAD_DB_USER="$(env_get RADIUS_DB_USER)"; RAD_DB_USER="${RAD_DB_USER:-radius}"
RAD_DB_PASS="$(env_get RADIUS_DB_PASSWORD)"
RAD_DB_HOST="$(env_get RADIUS_DB_HOST)"; RAD_DB_HOST="${RAD_DB_HOST:-127.0.0.1}"
RAD_DB_PORT="$(env_get RADIUS_DB_PORT)"; RAD_DB_PORT="${RAD_DB_PORT:-3306}"

DATA_DIR="$(env_get DBMS_DATA)"; DATA_DIR="${DATA_DIR:-$APP_DIR/data}"

mkdir -p "$DEST"; chmod 700 "$DEST"
MYCNF="$(mktemp)"; chmod 600 "$MYCNF"; trap 'rm -f "$MYCNF"' EXIT

say "1. Database dumps"
printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' "$DBMS_DB_USER" "$DBMS_DB_PASS" "$DBMS_DB_HOST" "$DBMS_DB_PORT" > "$MYCNF"
DBMS_SQL="$DEST/dbms-$STAMP.sql.gz"
mysqldump --defaults-extra-file="$MYCNF" --single-transaction --quick --routines --no-tablespaces "$DBMS_DB_NAME" | gzip > "$DBMS_SQL"
chmod 600 "$DBMS_SQL"
ok "$DBMS_DB_NAME -> $(basename "$DBMS_SQL") ($(du -h "$DBMS_SQL" | cut -f1))"

if [ -n "$RAD_DB_PASS" ]; then
  printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' "$RAD_DB_USER" "$RAD_DB_PASS" "$RAD_DB_HOST" "$RAD_DB_PORT" > "$MYCNF"
  RAD_SQL="$DEST/radius-$STAMP.sql.gz"
  mysqldump --defaults-extra-file="$MYCNF" --single-transaction --quick --no-tablespaces "$RAD_DB_NAME" | gzip > "$RAD_SQL"
  chmod 600 "$RAD_SQL"
  ok "$RAD_DB_NAME -> $(basename "$RAD_SQL") ($(du -h "$RAD_SQL" | cut -f1))"
else
  echo "  RADIUS_DB_PASSWORD is empty in $ENV_FILE; skipping the radius database dump."
fi

say "2. Encryption keys and SSH host keys"
KEEP_LIST=()
for f in "$DATA_DIR/secret.key" "$DATA_DIR/session.key" "$DATA_DIR/known_hosts"; do
  [ -e "$f" ] && KEEP_LIST+=("$f")
done
[ -d "$DATA_DIR/hostkeys" ] && KEEP_LIST+=("$DATA_DIR/hostkeys")
if [ "${#KEEP_LIST[@]}" -eq 0 ]; then
  die "Neither secret.key nor session.key was found under $DATA_DIR - check DBMS_DATA / APP_DIR"
fi
KEYS_TAR="$DEST/keys-$STAMP.tar.gz"
tar -czf "$KEYS_TAR" -C / "${KEEP_LIST[@]#/}"
chmod 600 "$KEYS_TAR"
ok "secret.key, session.key and SSH host keys -> $(basename "$KEYS_TAR")"

if [ "$WITH_CONFIGS" = 1 ] && [ -d "$DATA_DIR/backups" ]; then
  say "Optional: saved device configuration backups (--with-configs)"
  CONF_TAR="$DEST/device-configs-$STAMP.tar.gz"
  tar -czf "$CONF_TAR" -C "$DATA_DIR" backups
  chmod 600 "$CONF_TAR"
  ok "data/backups/ -> $(basename "$CONF_TAR") ($(du -h "$CONF_TAR" | cut -f1))"
fi

say "Housekeeping"
REMOVED="$(find "$DEST" -maxdepth 1 -type f -mtime "+$KEEP_DAYS" -print -delete | wc -l)"
echo "  removed $REMOVED archive(s) older than $KEEP_DAYS day(s) from $DEST"

say "Result"
printf '  \033[1;32mDone.\033[0m Saved in %s:\n' "$DEST"
ls -lh "$DEST" | tail -n +2 | awk '{printf "    %s  %s\n", $5, $NF}'
cat <<EOF

  IMPORTANT: this only writes to $DEST, on THIS server. If this server or its disk is lost, this copy is
  lost with it. Copy $DEST to another machine or off-site storage regularly, for example:
    rsync -a $DEST/ user@backup-host:/path/to/dbms-dr/
  Add this script to root's crontab for a daily, unattended backup (see the comment at the top of this file).
EOF
